import concurrent.futures
import socket
from ipaddress import ip_address
from urllib.parse import urljoin, urlparse

import httpx


class RuleImportError(Exception):
    def __init__(self, status_code: int, detail: str):
        """保存可直接映射为 HTTP 响应的导入错误信息。"""
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def import_rules_payload_from_url(
    url: str,
    *,
    client_factory=httpx.Client,
    public_host_checker=None,
) -> list[dict]:
    """从公开 HTTP(S) 地址导入规则 JSON，并限制重定向和 DNS rebinding。"""
    public_host_checker = public_host_checker or require_public_host
    current_url = url
    parsed = urlparse(current_url)
    if parsed.scheme not in {"http", "https"}:
        raise RuleImportError(422, "Only http/https URLs are allowed")

    try:
        with client_factory(timeout=15.0, follow_redirects=False) as client:
            for _ in range(5):
                parsed = urlparse(current_url)
                if parsed.scheme not in {"http", "https"}:
                    raise RuleImportError(422, "Only http/https URLs are allowed")

                before_ips = public_host_checker(parsed.hostname)
                resp = client.get(current_url)
                after_ips = public_host_checker(parsed.hostname)
                if before_ips != after_ips:
                    raise RuleImportError(422, "Host IP changed during request — DNS rebinding blocked")

                if resp.status_code in {301, 302, 303, 307, 308}:
                    location = resp.headers.get("Location")
                    if not location:
                        raise RuleImportError(422, "Redirect response missing Location header")
                    current_url = urljoin(current_url, location)
                    continue

                resp.raise_for_status()
                break
            else:
                raise RuleImportError(422, "Too many redirects while importing rules")
    except httpx.HTTPError as exc:
        raise RuleImportError(502, f"Failed to fetch rules from URL: {exc}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuleImportError(422, "URL response is not valid JSON") from exc
    if isinstance(data, dict) and isinstance(data.get("rules"), list):
        return data["rules"]
    if isinstance(data, list):
        return data
    raise RuleImportError(422, "Imported JSON must be an array or {\"rules\": [...]}")


def require_public_host(hostname: str | None) -> set[str]:
    """解析主机名并拒绝内网、保留、多播或未指定地址。"""
    if not hostname:
        raise RuleImportError(422, "URL must include a hostname")
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(socket.getaddrinfo, hostname, None)
            addrs = future.result(timeout=30.0)
    except (socket.gaierror, concurrent.futures.TimeoutError, ValueError) as exc:
        raise RuleImportError(422, "Unable to resolve host") from exc

    ips: set[str] = set()
    for _family, _type, _proto, _name, sockaddr in addrs:
        try:
            ip = ip_address(sockaddr[0])
        except ValueError:
            continue
        if (
            not ip.is_global
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
        ):
            raise RuleImportError(422, "Only public hosts are allowed")
        ips.add(str(ip))
    if not ips:
        raise RuleImportError(422, "No addresses resolved")
    return ips

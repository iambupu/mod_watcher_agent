from __future__ import annotations

import time
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models.settings import Setting
from app.services.llm_provider_config import provider_default_base_url

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
CONTROL_ENDPOINTS_SHARED_LAN = {
    "/api/logs/open-dir",
    "/api/settings/auto-start",
}
ACCESS_PROFILES = {"local_relaxed", "local_strict", "shared_lan"}
_POLICY_CACHE_TTL_SECONDS = 15.0
_policy_cache: dict[str, object] = {"expires_at": 0.0, "value": None}


def _normalize_host(value: str) -> str:
    """规范化内部数据，供后续流程使用。"""
    host = (value or "").strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host


def _host_to_ip(host: str):
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    try:
        return ip_address(host)
    except ValueError:
        return None


def _is_truthy(value: str | bool | None) -> bool:
    """判断内部条件是否成立。"""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_ip_literal(host: str) -> bool:
    """判断内部条件是否成立。"""
    return _host_to_ip(_normalize_host(host)) is not None


def is_loopback_host(host: str) -> bool:
    """判断条件是否成立。"""
    normalized = _normalize_host(host)
    if normalized in LOCAL_HOSTS:
        return True
    ip = _host_to_ip(normalized)
    return bool(ip and ip.is_loopback)


def is_private_or_loopback_host(host: str) -> bool:
    """判断条件是否成立。"""
    normalized = _normalize_host(host)
    if normalized == "localhost":
        return True
    ip = _host_to_ip(normalized)
    if not ip:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local)


def is_local_request(request: Request) -> bool:
    """判断条件是否成立。"""
    host = request.client.host if request.client else ""
    return is_loopback_host(host)


def is_lan_request(request: Request) -> bool:
    """判断条件是否成立。"""
    host = request.client.host if request.client else ""
    normalized = _normalize_host(host)
    if normalized in LOCAL_HOSTS:
        return True
    ip = _host_to_ip(normalized)
    if not ip:
        return False
    return bool(ip.is_loopback or ip.is_private)


def require_safe_bind_host() -> None:
    """校验必需条件，不满足时抛出异常。"""
    profile = (settings.MW_ACCESS_PROFILE or "local_relaxed").strip().lower()
    bind_host = settings.MW_BIND_HOST
    if profile == "local_relaxed" and not is_loopback_host(bind_host):
        raise RuntimeError(
            "Unsafe bind host configuration: MW_ACCESS_PROFILE=local_relaxed requires "
            f"loopback bind host, got MW_BIND_HOST={bind_host!r}"
        )


@dataclass
class RuntimePolicy:
    profile: str
    allow_lan: bool
    admin_token: str


def _load_runtime_policy(force_refresh: bool = False) -> RuntimePolicy:
    """加载内部流程需要的配置或数据。"""
    now = time.monotonic()
    cached = _policy_cache.get("value")
    expires_at = float(_policy_cache.get("expires_at") or 0.0)
    if not force_refresh and isinstance(cached, RuntimePolicy) and now < expires_at:
        return cached

    profile = (settings.MW_ACCESS_PROFILE or "local_relaxed").strip().lower()
    allow_lan = bool(settings.MW_ALLOW_LAN)
    admin_token = settings.MW_ADMIN_TOKEN

    try:
        with Session(engine) as session:
            rows = session.exec(
                select(Setting).where(Setting.key.in_(["access_profile", "allow_lan"]))
            ).all()
        values = {row.key: row.value for row in rows}
        profile = (values.get("access_profile") or profile).strip().lower()
        allow_lan = _is_truthy(values.get("allow_lan")) if "allow_lan" in values else allow_lan
    except Exception:
        # Keep runtime availability even if DB is temporarily unavailable.
        pass

    if profile not in ACCESS_PROFILES:
        profile = "local_relaxed"

    policy = RuntimePolicy(profile=profile, allow_lan=allow_lan, admin_token=admin_token)
    _policy_cache["value"] = policy
    _policy_cache["expires_at"] = now + _POLICY_CACHE_TTL_SECONDS
    return policy


@dataclass
class AccessDecision:
    allow: bool
    status_code: int = 200
    detail: str = ""
    set_cookie: str | None = None


class AccessPolicy:
    def __init__(self) -> None:
        """初始化实例并保存运行所需的依赖。"""
        policy = _load_runtime_policy()
        self.profile = policy.profile
        self.allow_lan = policy.allow_lan
        self.admin_token = policy.admin_token

    def _allow_source(self, request: Request) -> bool:
        """判断内部访问策略是否允许继续。"""
        if self.profile in {"local_relaxed", "local_strict"}:
            return is_local_request(request)
        if self.profile == "shared_lan":
            return is_lan_request(request) if self.allow_lan else is_local_request(request)
        return is_local_request(request)

    # Endpoints that never require a token (login, logout, status).
    _TOKEN_EXEMPT_PREFIXES = ("/api/auth/",)

    def _token_required(self, path: str) -> bool:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        if not path.startswith("/api/"):
            return False
        for prefix in self._TOKEN_EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return False
        return self.profile in {"local_strict", "shared_lan"}

    def evaluate(self, request: Request) -> AccessDecision:
        """处理当前模块的业务逻辑并返回结果。"""
        path = request.url.path or ""
        if not path.startswith("/api/"):
            return AccessDecision(allow=True)

        if not self._allow_source(request):
            return AccessDecision(
                allow=False,
                status_code=403,
                detail="Remote API access is disabled on this instance",
            )

        if self.profile == "shared_lan" and path in CONTROL_ENDPOINTS_SHARED_LAN and not is_local_request(request):
            return AccessDecision(
                allow=False,
                status_code=403,
                detail="This control endpoint is restricted to local machine in shared_lan profile",
            )

        if not self._token_required(path):
            return AccessDecision(allow=True)

        if not self.admin_token:
            return AccessDecision(
                allow=False,
                status_code=503,
                detail="MW_ADMIN_TOKEN is required for this access profile",
            )

        # Prefer httpOnly cookie over header (defence-in-depth against XSS).
        cookie_token = request.cookies.get("mw_session", "").strip()
        if cookie_token and cookie_token == self.admin_token:
            return AccessDecision(allow=True)

        token = request.headers.get("X-Mod-Watcher-Token", "").strip()
        if not token:
            return AccessDecision(
                allow=False,
                status_code=401,
                detail="Missing X-Mod-Watcher-Token",
            )
        if token != self.admin_token:
            return AccessDecision(
                allow=False,
                status_code=401,
                detail="Invalid X-Mod-Watcher-Token",
            )
        # Auto-migrate: set httpOnly cookie so subsequent requests don't need
        # the header and the frontend can clear localStorage.
        return AccessDecision(allow=True, set_cookie=self.admin_token)


def _provider_default_base_url(provider: str) -> str:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return provider_default_base_url(provider)


def validate_outbound_url(provider: str, base_url: str) -> str:
    """校验输入是否符合业务约束。"""
    resolved = (base_url or "").strip() or _provider_default_base_url(provider)
    parsed = urlparse(resolved)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise HTTPException(status_code=422, detail=f"Unsupported outbound URL scheme: {scheme or 'empty'}")

    host = _normalize_host(parsed.hostname or "")
    if not host:
        raise HTTPException(status_code=422, detail="Outbound URL host is required")

    try:
        if parsed.port is not None and (parsed.port <= 0 or parsed.port > 65535):
            raise HTTPException(status_code=422, detail="Outbound URL port is invalid")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Outbound URL port is invalid") from exc

    provider_name = (provider or "").strip().lower()
    if provider_name == "ollama":
        if not settings.MW_ALLOW_LOCAL_LLM:
            raise HTTPException(status_code=422, detail="Local LLM access is disabled by MW_ALLOW_LOCAL_LLM")
        if host not in {"localhost", "127.0.0.1"}:
            raise HTTPException(status_code=422, detail="Ollama outbound URL must use localhost or 127.0.0.1")
        return resolved

    if scheme != "https":
        raise HTTPException(status_code=422, detail=f"Provider '{provider_name or 'unknown'}' requires https base_url")

    if is_private_or_loopback_host(host):
        raise HTTPException(status_code=422, detail="Private/loopback outbound URL is blocked for non-local providers")

    return resolved

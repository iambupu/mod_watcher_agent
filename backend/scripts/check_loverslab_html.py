"""Quick checker for LoversLab page fetch with user-provided cookies.

Usage (PowerShell):
  $env:LL_COOKIE="cf_clearance=...; ips4_member_id=...; ..."
  ..\\.venv\\Scripts\\python.exe scripts\\check_loverslab_html.py `
      --url "https://www.loverslab.com/files/category/319-x-change-life/" `
      --referer "https://www.loverslab.com/files/category/161-the-sims-4/" `
      --save "tmp\\ll-page.html"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import httpx

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)


def _extract_title(html: str) -> str:
    matched = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not matched:
        return ""
    return re.sub(r"\s+", " ", matched.group(1)).strip()


def _is_cloudflare_challenge(html: str) -> bool:
    lowered = html.lower()
    return (
        "just a moment..." in lowered and "challenges.cloudflare.com" in lowered
    ) or ("__cf_chl_" in lowered and "enable javascript and cookies to continue" in lowered)


def _looks_like_loverslab_listing(html: str) -> bool:
    lowered = html.lower()
    return (
        "/files/file/" in lowered
        or "ipsdatalist" in lowered
        or "available rss feeds" in lowered
        or "ipslayout_contentarea" in lowered
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Check if LoversLab returns real HTML or challenge page.")
    parser.add_argument("--url", required=True, help="Target LoversLab URL.")
    parser.add_argument(
        "--cookie",
        default="",
        help="Raw cookie header. If omitted, read from LL_COOKIE env var.",
    )
    parser.add_argument("--referer", default="", help="Optional Referer header.")
    parser.add_argument("--ua", default=DEFAULT_UA, help="User-Agent header.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification.")
    parser.add_argument("--save", default="", help="Optional path to save response HTML.")
    args = parser.parse_args()

    cookie_value = args.cookie
    if not cookie_value:
        from os import getenv

        cookie_value = getenv("LL_COOKIE", "")

    if not cookie_value:
        print("error: cookie is empty. pass --cookie or set LL_COOKIE env var.")
        return 2

    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "cache-control": "max-age=0",
        "upgrade-insecure-requests": "1",
        "user-agent": args.ua,
        "cookie": cookie_value,
    }
    if args.referer:
        headers["referer"] = args.referer

    try:
        with httpx.Client(
            headers=headers,
            timeout=httpx.Timeout(args.timeout),
            follow_redirects=True,
            verify=not args.insecure,
        ) as client:
            response = client.get(args.url)
    except Exception as exc:  # noqa: BLE001
        print(f"request_error: {type(exc).__name__}: {exc}")
        return 1

    body = response.text
    title = _extract_title(body)
    cf = _is_cloudflare_challenge(body)
    looks_listing = _looks_like_loverslab_listing(body)

    print(f"status={response.status_code}")
    print(f"final_url={response.url}")
    print(f"title={title!r}")
    print(f"content_length={len(body)}")
    print(f"cloudflare_challenge={cf}")
    print(f"looks_like_listing_html={looks_listing}")

    if args.save:
        path = Path(args.save)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        print(f"saved_html={path.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""LoversLab RSS/Atom feed adapter with streaming fetch and size protection.

Fetches feed bytes via httpx with Content-Length pre-check and chunk
accumulation limit.  Parses with feedparser, then normalises entries
into ModItem with stable source_id (sha256 of canonicalised file URL).
"""

import asyncio
import calendar
import hashlib
import logging
import os
import re
import sys
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import feedparser
import httpx
from selectolax.parser import HTMLParser

from app.adapters.base import BaseAdapter
from app.adapters.loverslab_common import (
    is_allowed_loverslab_url,
    loverslab_mod_item_from_raw,
    validate_loverslab_url,
)
from app.models.mod_item import ModItem
from app.schemas.watch_rule import LoversLabRuleConfig
from app.services.loverslab.constants import LOVERSLAB_HOSTS, LOVERSLAB_STATIC_HOSTS
from app.services.loverslab.url_utils import extract_loverslab_file_id_from_url
from app.utils.time import parse_utc_datetime

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = LOVERSLAB_HOSTS | LOVERSLAB_STATIC_HOSTS
MAX_FEED_BYTES = 5 * 1024 * 1024  # 5 MB
REQUEST_TIMEOUT = 30.0
MAX_ENTRIES_PER_FEED_URL = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class LoversLabFeedAdapter(BaseAdapter):
    """RSS/Atom feed adapter for LoversLab.

    Fetches feed bytes via httpx streaming with size guard, then parses
    with feedparser.  Does **not** fall back to the global file feed when
    *feedUrls* is empty — caller must configure URLs explicitly.
    """

    # Silence abstract-method warning: BaseAdapter requires fetch_mod_detail
    # and normalize, both provided below.

    def __init__(self, **kwargs: Any) -> None:
        """延迟创建 HTTP 客户端，便于复用连接并按需读取代理配置。"""
        _ = kwargs
        self._client: httpx.AsyncClient | None = None

    # ── HTTP helpers ────────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        """返回带 UA、超时和代理设置的共享 httpx 客户端。"""
        if self._client is None:
            proxy = self._detect_proxy()
            kwargs: dict[str, Any] = {
                "timeout": httpx.Timeout(REQUEST_TIMEOUT),
                "headers": {"User-Agent": USER_AGENT},
                "follow_redirects": False,
            }
            if proxy:
                kwargs["proxy"] = proxy
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def aclose(self) -> None:
        """Close shared HTTP client to avoid connection/resource leaks."""
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    @staticmethod
    def _detect_proxy() -> str | None:
        """Detect proxy: env var → Windows IE/Edge system proxy → None."""
        for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
            val = os.environ.get(var) or os.environ.get(var.lower())
            if val:
                return val
        # Windows: read IE/Edge proxy settings from registry.
        if sys.platform == "win32":
            try:
                import winreg  # noqa: F811
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                ) as key:
                    server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    if server:
                        # Registry stores "host:port" without scheme.
                        if not server.startswith("http://") and not server.startswith("https://"):
                            server = "http://" + server
                        return server
            except (ImportError, OSError, ValueError):
                pass
        return None

    async def _fetch_feed_bytes(self, url: str) -> bytes:
        """Stream-fetch *url* with Content-Length and chunk-size guards."""
        current_url = validate_loverslab_url(url, kind="RSS", allowed_hosts=ALLOWED_HOSTS)
        client = await self._get_client()
        for _ in range(5):
            async with client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("Redirect response missing Location header")
                    current_url = validate_loverslab_url(urljoin(current_url, location), kind="RSS", allowed_hosts=ALLOWED_HOSTS)
                    continue

                return await self._read_checked_feed_response(response)
        raise ValueError("Too many redirects while fetching LoversLab RSS")

    async def _read_checked_feed_response(self, response: httpx.Response) -> bytes:
        """读取 RSS 响应体，同时检查状态码、跳转域名和最大体积。"""
        response.raise_for_status()

        final_url = str(response.url)
        if not is_allowed_loverslab_url(final_url, ALLOWED_HOSTS):
            raise ValueError(f"Redirected to disallowed host: {final_url}")

        cl = response.headers.get("Content-Length")
        if cl:
            try:
                size = int(cl)
            except ValueError:
                size = 0
            if size > MAX_FEED_BYTES:
                raise ValueError("RSS payload too large")

        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > MAX_FEED_BYTES:
                raise ValueError("RSS payload too large")
        return bytes(data)

    @staticmethod
    def _is_cloudflare_body(text: str) -> bool:
        """识别 RSS 响应是否其实是 Cloudflare challenge 页面。"""
        return "cloudflare" in text.lower() and "challenge" in text.lower()

    # ── BaseAdapter interface ────────────────────────────────────────────

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        """Parse config, fetch feed bytes, normalise entries.

        When *feedUrls* is empty the result is an empty list — no fallback.
        """
        config = LoversLabRuleConfig.model_validate_json(source_config_json)
        if not config.feedUrls:
            return []

        raw_results: list[dict] = []
        for url in config.feedUrls:
            payload = await self._fetch_feed_bytes(url)
            preview = payload[:4096].decode("utf-8", errors="ignore")
            if self._is_cloudflare_body(preview):
                raise ValueError("Cloudflare challenge detected")

            feed = await asyncio.to_thread(feedparser.parse, payload)
            if getattr(feed, "bozo", 0):
                exc = getattr(feed, "bozo_exception", None)
                msg = str(exc or "")
                if "cloudflare" in msg.lower() or "challenge" in msg.lower():
                    raise ValueError("Cloudflare challenge detected")
                raise ValueError("Invalid RSS/Atom feed")

            for entry in list(feed.entries)[:MAX_ENTRIES_PER_FEED_URL]:
                raw = self._normalize_entry(entry, config)
                if raw:
                    raw_results.append(raw)

        # Deduplicate by external_id across URLs, keep newest.
        seen: dict[str, dict] = {}
        for item in raw_results:
            key = item["external_id"]
            existing = seen.get(key)
            if not existing or (item.get("updatedAt") or "") > (existing.get("updatedAt") or ""):
                seen[key] = item

        sorted_items = sorted(
            seen.values(),
            key=lambda x: x.get("updatedAt") or x.get("publishedAt") or "",
            reverse=True,
        )
        capped = sorted_items[: config.maxItemsPerRun]
        return [self.normalize(item) for item in capped]

    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> ModItem | None:
        """RSS 来源不支持单条详情补全，统一返回 None。"""
        _ = (external_id, game_domain)
        return None

    def normalize(self, raw_item: dict) -> ModItem:
        """Build ModItem with *updated_at* guaranteed as ``datetime | None``."""
        return loverslab_mod_item_from_raw(raw_item)

    # ── Entry normalisation ─────────────────────────────────────────────

    def _normalize_entry(self, entry, config: LoversLabRuleConfig) -> dict | None:
        """把 feedparser entry 转换为入库原始字段，过滤没有真实文件链接的主题。"""
        link = (entry.get("link", "") or "").strip()
        if not link:
            return None

        # Forum topic RSS: link is /topic/..., but description HTML
        # contains the actual file URL via View File button.
        if "/files/file/" not in link:
            file_url = self._extract_file_url_from_description(entry)
            if file_url:
                link = file_url

        external_id = self._build_source_id(link)
        # Skip entries that have no actual file link (hash fallback only).
        if self._is_hash_id(external_id):
            return None
        updated_at = self._parse_feed_datetime(entry)
        published_at = self._parse_published_iso(entry)
        tags = self._extract_tags(entry)
        summary_html = self._extract_summary_html(entry)
        summary = self._clean_summary(summary_html)

        return {
            "source": "loverslab",
            "external_id": external_id,
            "game": config.gameLabel,
            "game_domain": None,
            "title": (entry.get("title", "") or "")[:512],
            "url": link,
            "author": entry.get("author", None),
            "category": tags[0] if tags else None,
            "categories": tags[:1] if tags else [],
            "tags": tags,
            "original_summary": summary,
            "original_summary_html": summary_html[:2000] if summary_html else "",
            "version": None,
            "created_at_remote": None,
            "createdAt": None,
            "updated_at_remote": updated_at,
            "updatedAt": updated_at.isoformat() if updated_at is not None else None,
            "published_at_remote": published_at,
            "publishedAt": published_at,
            "downloads": None,
            "unique_downloads": None,
            "endorsements": None,
            "views": None,
            "likes": None,
            "adult_content": True,
            "thumbnail_url": (
                entry.get("media_thumbnail", [{}])[0].get("url")
                if entry.get("media_thumbnail")
                else None
            ),
        }

    # ── Source ID ───────────────────────────────────────────────────────

    @staticmethod
    def _build_source_id(link: str) -> str:
        """Stable source ID from the canonical file URL.

        Tries, in order:
          1. ``/files/file/<digits>`` from the link.
          2. ``sha256(canonicalised_url)[:16]`` hash fallback.
        """
        file_id = extract_loverslab_file_id_from_url(link)
        if file_id:
            return file_id
        canonical = LoversLabFeedAdapter._canonicalize_url(link)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _is_hash_id(source_id: str) -> bool:
        """True when *source_id* is the 16-char hex hash fallback."""
        return bool(re.fullmatch(r"[0-9a-f]{16}", source_id))

    @staticmethod
    def _extract_file_url_from_description(entry: Any) -> str | None:
        """从论坛主题 RSS 描述里的 View File 链接提取真实文件 URL。"""
        html = LoversLabFeedAdapter._extract_summary_html(entry)
        if not html:
            return None
        matched = re.search(r'(https?://[^"\s]*?files/file/\d+[^"\s]*)', html)
        return matched.group(1) if matched else None

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        """规范化 URL 后用于哈希兜底，降低协议和尾斜杠造成的重复。"""
        url = url.lower().strip()
        for prefix in ("https://", "http://"):
            if url.startswith(prefix):
                url = url[len(prefix) :]
        return url.rstrip("/")

    # ─── Tag / summary extraction ──────────────────────────────────────

    @staticmethod
    def _extract_tags(entry: Any) -> list[str]:
        """兼容 feedparser 的 dict 标签和字符串标签两种形态。"""
        out: list[str] = []
        for t in entry.get("tags") or []:
            if isinstance(t, dict):
                term = t.get("term") or t.get("label") or ""
                if term:
                    out.append(str(term))
            elif isinstance(t, str):
                out.append(t)
        return out

    @staticmethod
    def _extract_summary_html(entry: Any) -> str:
        """按 RSS 常见字段顺序提取摘要 HTML。"""
        for key in ("summary", "description"):
            val = entry.get(key)
            if val:
                return str(val)
        contents = entry.get("content") or []
        if contents and isinstance(contents, list):
            first = contents[0] or {}
            val = first.get("value")
            if val:
                return str(val)
        return ""

    @staticmethod
    def _clean_summary(html: str) -> str:
        """清理摘要 HTML 中不可见/脚本内容，并压缩为空白文本。"""
        if not html:
            return ""
        tree = HTMLParser(html)
        for node in tree.css("script,style,iframe,noscript"):
            node.decompose()
        text = tree.body.text(separator=" ") if tree.body else tree.text()
        lines = [line.strip() for line in text.split("\n")]
        compact = " ".join(line for line in lines if line)
        return re.sub(r"\s+", " ", compact).strip()[:1000]

    # ── Date helpers ────────────────────────────────────────────────────

    @staticmethod
    def _parse_feed_datetime(entry) -> datetime | None:
        """优先解析 feedparser 的 struct_time，再回退原始字符串时间。"""
        for key in ("updated_parsed", "published_parsed"):
            parsed = entry.get(key)
            if parsed:
                try:
                    return datetime.fromtimestamp(
                        calendar.timegm(parsed), tz=UTC
                    )
                except (ValueError, TypeError, OverflowError):
                    continue
        for key in ("updated", "published"):
            raw = entry.get(key)
            if raw:
                parsed = parse_utc_datetime(raw)
                if parsed is not None:
                    return parsed
        return None

    @staticmethod
    def _parse_published_iso(entry) -> str | None:
        """提取发布时间并统一输出 ISO 字符串。"""
        pp = entry.get("published_parsed")
        if pp:
            try:
                return datetime.fromtimestamp(
                    calendar.timegm(pp), tz=UTC
                ).isoformat()
            except (ValueError, TypeError, OverflowError):
                pass
        raw = entry.get("published") or entry.get("pubDate")
        if raw:
            parsed = parse_utc_datetime(raw)
            if parsed is not None:
                return parsed.isoformat()
        return None

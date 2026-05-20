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
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx
from selectolax.parser import HTMLParser

from app.adapters.base import BaseAdapter
from app.models.mod_item import ModItem
from app.schemas.watch_rule import LoversLabRuleConfig

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = {"www.loverslab.com", "loverslab.com", "static.loverslab.com"}
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
        self._client: httpx.AsyncClient | None = None

    # ── HTTP helpers ────────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
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
        current_url = self._validate_loverslab_url(url)
        client = await self._get_client()
        for _ in range(5):
            async with client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("Redirect response missing Location header")
                    current_url = self._validate_loverslab_url(urljoin(current_url, location))
                    continue

                return await self._read_checked_feed_response(response)
        raise ValueError("Too many redirects while fetching LoversLab RSS")

    async def _read_checked_feed_response(self, response: httpx.Response) -> bytes:
        response.raise_for_status()

        final_url = str(response.url)
        if not self._is_allowed_loverslab_url(final_url):
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

    @classmethod
    def _validate_loverslab_url(cls, url: str) -> str:
        normalized = (url or "").strip()
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("LoversLab RSS URL must be an absolute http(s) URL")
        if not cls._is_allowed_loverslab_url(normalized):
            raise ValueError(f"LoversLab RSS URL host is not allowed: {normalized}")
        return normalized

    @staticmethod
    def _is_allowed_loverslab_url(url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return host in ALLOWED_HOSTS

    @staticmethod
    def _is_cloudflare_body(text: str) -> bool:
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
        return None

    def normalize(self, raw_item: dict) -> ModItem:
        """Build ModItem with *updated_at* guaranteed as ``datetime | None``."""
        updated_value: Any = raw_item.get("updated_at_remote")
        updated_at: datetime | None = None
        if isinstance(updated_value, datetime):
            updated_at = updated_value
        elif isinstance(updated_value, str):
            try:
                parsed = datetime.fromisoformat(updated_value.replace("Z", "+00:00"))
                updated_at = (
                    parsed
                    if parsed.tzinfo is not None
                    else parsed.replace(tzinfo=UTC)
                )
            except (ValueError, TypeError):
                updated_at = None

        return ModItem(
            source_id=raw_item.get("external_id", ""),
            source=raw_item.get("source", "loverslab"),
            name=raw_item.get("title", ""),
            game=raw_item.get("game", ""),
            url=raw_item.get("url", ""),
            summary=raw_item.get("original_summary") or "",
            author=raw_item.get("author") or "",
            downloads=raw_item.get("downloads") or 0,
            endorsements=raw_item.get("endorsements") or 0,
            likes=raw_item.get("likes") or 0,
            categories=raw_item.get("categories", []),
            tags=raw_item.get("tags", []),
            thumbnail_url=raw_item.get("thumbnail_url") or "",
            updated_at=updated_at,
            is_adult=raw_item.get("adult_content", False),
            raw=raw_item,
        )

    # ── Entry normalisation ─────────────────────────────────────────────

    def _normalize_entry(self, entry, config: LoversLabRuleConfig) -> dict | None:
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
        matched = re.search(r"/files/file/(\d+)", link)
        if matched:
            return matched.group(1)
        canonical = LoversLabFeedAdapter._canonicalize_url(link)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _is_hash_id(source_id: str) -> bool:
        """True when *source_id* is the 16-char hex hash fallback."""
        return bool(re.fullmatch(r"[0-9a-f]{16}", source_id))

    @staticmethod
    def _extract_file_url_from_description(entry: Any) -> str | None:
        html = LoversLabFeedAdapter._extract_summary_html(entry)
        if not html:
            return None
        matched = re.search(r'(https?://[^"\s]*?files/file/\d+[^"\s]*)', html)
        return matched.group(1) if matched else None

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        url = url.lower().strip()
        for prefix in ("https://", "http://"):
            if url.startswith(prefix):
                url = url[len(prefix) :]
        return url.rstrip("/")

    # ─── Tag / summary extraction ──────────────────────────────────────

    @staticmethod
    def _extract_tags(entry: Any) -> list[str]:
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
                try:
                    return datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _parse_published_iso(entry) -> str | None:
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
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
            except (ValueError, TypeError):
                pass
        return None

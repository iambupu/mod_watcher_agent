import asyncio
import logging
import random
import re
from urllib.parse import urljoin, urlsplit

import httpx
from selectolax.parser import HTMLParser

from app.adapters.base import BaseAdapter
from app.adapters.loverslab_common import loverslab_mod_item_from_raw
from app.models.mod_item import ModItem
from app.schemas.watch_rule import LoversLabRuleConfig
from app.services.browser import BrowserPageFetcher
from app.services.loverslab.category_parser import parse_category_items

logger = logging.getLogger(__name__)

BASE_URL = "https://www.loverslab.com/files/file/{ext_id}/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30.0
MIN_DELAY = 1.0
MAX_DELAY = 3.0
ALLOWED_HOSTS = {"www.loverslab.com", "loverslab.com"}


class LoversLabPageAdapter(BaseAdapter):
    """Adapter for scraping LoversLab mod detail pages with selectolax.

    Enriches mod data from individual file detail pages, extracting
    version, download stats, description, images, changelog, and
    update timestamps that are not available from the RSS feed.

    Note: this class is not auto-registered (source = None).
    Use LoversLabAdapter (source = "loverslab") for unified dispatch.
    """

    def __init__(self, **kwargs):
        """初始化实例并保存运行所需的依赖。"""
        self._client: httpx.AsyncClient | None = None
        self._page_fetcher: BrowserPageFetcher = kwargs.get("page_fetcher") or BrowserPageFetcher()

    async def _get_client(self) -> httpx.AsyncClient:
        """读取内部状态或派生结果。"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(REQUEST_TIMEOUT),
                headers={"User-Agent": USER_AGENT},
                follow_redirects=False,
            )
        return self._client

    async def _get_allowed_url(self, url: str) -> httpx.Response:
        """读取内部状态或派生结果。"""
        current_url = self._validate_loverslab_url(url)
        client = await self._get_client()
        for _ in range(5):
            response = await client.get(current_url)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                await response.aclose()
                if not location:
                    raise ValueError("Redirect response missing Location header")
                current_url = self._validate_loverslab_url(urljoin(current_url, location))
                continue
            final_url = str(getattr(response, "url", "") or current_url)
            if not final_url.startswith(("http://", "https://")):
                final_url = current_url
            if not self._is_allowed_loverslab_url(final_url):
                await response.aclose()
                raise ValueError(f"Redirected to disallowed host: {final_url}")
            return response
        raise ValueError("Too many redirects while fetching LoversLab page")

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        """Discover mods via page scraping from configured page URLs.

        Parses the JSON config, scrapes each listing page for mod links,
        then enriches results via per-mod detail pages.

        Args:
            source_config_json: JSON string parsable to LoversLabRuleConfig.

        Returns:
            List of normalized ModItem results.
        """
        config = LoversLabRuleConfig.model_validate_json(source_config_json)

        if not config.pageUrls:
            return []

        all_items: list[ModItem] = []
        seen_external_ids: set[str] = set()
        for page_url in config.pageUrls:
            if len(all_items) >= config.maxItemsPerRun:
                break

            result = await self._page_fetcher.fetch_html(
                page_url,
                profile_name=config.browserProfile or "loverslab",
                headless=False,
            )
            if result.status != "ok":
                raise ValueError(
                    f"LoversLab browser fetch failed for {page_url}: {result.status}"
                    + (f" ({result.error})" if result.error else "")
                )
            if not self._is_allowed_loverslab_url(result.final_url or page_url):
                raise ValueError(f"Redirected to disallowed host: {result.final_url}")

            html = result.html
            if not html or len(html) < 50:
                logger.warning("Empty listing page HTML for %s", page_url)
                continue
            if self._is_cloudflare_challenge_html(html):
                raise ValueError(
                    "Cloudflare challenge detected when fetching LoversLab page URL. "
                    "Try accessMode='rss' first, or use a reachable page URL."
                )

            category_items = parse_category_items(
                html,
                result.final_url or page_url,
                game_label=config.gameLabel,
                max_items=config.maxItemsPerRun - len(all_items),
            )
            if not category_items:
                raise ValueError(
                    "LoversLab category structure changed: page was reachable, "
                    "but no /files/file/ items were parsed."
                )

            for item in category_items:
                if len(all_items) >= config.maxItemsPerRun:
                    break
                if item.source_id in seen_external_ids:
                    continue
                seen_external_ids.add(item.source_id)
                all_items.append(item)

        return all_items

    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> ModItem | None:
        """Scrape a LoversLab file detail page for enriched mod data.

        Args:
            external_id: The LoversLab file ID number.
            game_domain: Unused for LoversLab (single domain).

        Returns:
            A ModItem, or None if the page is unrecoverable.
        """
        file_id = self._extract_file_id_from_external_id(external_id)
        url = BASE_URL.format(ext_id=file_id)

        try:
            response = await self._get_allowed_url(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.info("LoversLab mod %s not found (404)", file_id)
                return None
            logger.warning(
                "HTTP %s fetching LoversLab mod %s: %s",
                exc.response.status_code,
                file_id,
                exc,
            )
            return None
        except httpx.TimeoutException:
            logger.warning(
                "Timeout fetching LoversLab mod %s (%.0fs)",
                file_id,
                REQUEST_TIMEOUT,
            )
            return None
        except httpx.RequestError as exc:
            logger.warning(
                "Request error fetching LoversLab mod %s: %s",
                file_id,
                exc,
            )
            return None
        finally:
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            await asyncio.sleep(delay)

        html = response.text
        if not html or len(html) < 50:
            logger.warning(
                "Empty or too-short HTML for LoversLab mod %s", external_id
            )
            return None
        if self._is_cloudflare_challenge_html(html):
            raise ValueError(
                f"Cloudflare challenge detected when fetching LoversLab mod detail page: {url}"
            )

        return self._parse_page(html, file_id, url, game_domain or "")

    def normalize(self, raw_item: dict) -> ModItem:
        """规范化输入数据，供后续流程使用。"""
        return loverslab_mod_item_from_raw(raw_item)

    def _parse_listing_links(
        self, html: str, base_url: str
    ) -> list[str]:
        """Extract file detail external IDs from a listing/category page.

        Scans for links matching /files/file/NNNN/ pattern.

        Args:
            html: Raw HTML of the listing page.
            base_url: The listing page URL (unused, kept for API compatibility).

        Returns:
            List of external_id strings found on the page.
        """
        tree = HTMLParser(html)
        external_ids: list[str] = []
        seen: set[str] = set()

        for candidate_url in (base_url,):
            ext_id = self._extract_external_id_from_url(candidate_url)
            if ext_id and ext_id not in seen:
                seen.add(ext_id)
                external_ids.append(ext_id)

        for link in tree.css("a[href]"):
            href = (link.attributes.get("href", "") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            ext_id = self._extract_external_id_from_url(urljoin(base_url, href))
            if not ext_id:
                continue
            if ext_id in seen:
                continue
            seen.add(ext_id)
            external_ids.append(ext_id)

        return external_ids

    def _parse_page(
        self, html: str, external_id: str, url: str, game_label: str
    ) -> dict | None:
        """Parse LoversLab file detail page HTML.

        Uses selectolax for CSS selector-based extraction. Multiple
        fallback selectors handle Invision Community 4.x variations.

        Args:
            html: Raw HTML of the file detail page.
            external_id: The LoversLab file ID.
            url: The page URL.
            game_label: Rule-configured game label.

        Returns:
            A normalized mod dict with all extractable fields, or
            a minimal dict (partial data) for parse errors.
        """
        tree = HTMLParser(html)

        title = self._extract_title(tree)
        author = self._extract_author(tree)
        description = self._extract_description(tree)
        version = self._extract_version(tree)
        downloads = self._extract_downloads(tree)
        file_size = self._extract_file_size(tree)
        images = self._extract_images(tree)
        updated_at = self._extract_updated_at(tree)
        changelog_raw = self._extract_changelog(tree)

        return {
            "source": "loverslab",
            "external_id": external_id,
            "game": game_label,
            "game_domain": None,
            "title": title or "",
            "url": url,
            "author": author,
            "category": None,
            "tags_json": "[]",
            "original_summary": description,
            "version": version,
            "created_at_remote": None,
            "updated_at_remote": updated_at,
            "published_at_remote": None,
            "downloads": downloads,
            "unique_downloads": None,
            "endorsements": None,
            "views": None,
            "likes": None,
            "adult_content": True,
            "thumbnail_url": images[0] if images else None,
            "changelog_raw": changelog_raw,
            "images": images,
            "file_size": file_size,
        }

    def _extract_title(self, tree: HTMLParser) -> str | None:
        """Extract mod title from the page heading."""
        return self._extract_first_text(
            tree,
            (
                "h1.ipsType_pageTitle",
                ".ipsType_pageTitle",
                "[data-role='fileTitle']",
            ),
        )

    def _extract_author(self, tree: HTMLParser) -> str | None:
        """Extract author name from the page."""
        return self._extract_first_text(
            tree,
            (
                "a[href*='/profile/']",
                ".ipsType_reset a[href*='user']",
            ),
        )

    def _extract_description(self, tree: HTMLParser) -> str | None:
        """Extract full mod description from content area."""
        return self._extract_first_text(
            tree,
            (
                ".ipsType_richText[data-role='content']",
                "[data-role='content']",
                ".cFile_content",
                "[data-role='fileContent']",
            ),
        )

    @staticmethod
    def _extract_first_text(
        tree: HTMLParser,
        selectors: tuple[str, ...],
    ) -> str | None:
        """从原始内容中提取目标字段。"""
        for selector in selectors:
            el = tree.css_first(selector)
            if el:
                text = el.text(strip=True)
                if text:
                    return text
        return None

    @staticmethod
    def _scan_labeled_text(
        tree: HTMLParser,
        predicate,
    ) -> str | None:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        for selector in ("li", "dt", "span", "div"):
            elements = tree.css(selector)
            for el in elements:
                text = el.text(strip=True).lower()
                if not predicate(text):
                    continue
                parent = el.parent
                if parent:
                    return parent.text(strip=True)
        return None

    def _extract_version(self, tree: HTMLParser) -> str | None:
        """Extract version number from the page.

        Tries structured data elements first, then falls back to
        scanning text for 'Version' labels.
        """
        version = self._extract_first_text(
            tree,
            (
                "[data-role='version']",
                ".cFile_version",
                "[itemprop='version']",
            ),
        )
        if version:
            return version

        # Scan for "Version:" label in list items or definition terms
        for selector in ("li", "dt", "span", "div"):
            elements = tree.css(selector)
            for el in elements:
                text = el.text(strip=True).lower()
                if text.startswith("version"):
                    # Try to get value from sibling or child
                    parent = el.parent
                    if parent:
                        full_text = parent.text(strip=True)
                        parts = full_text.split(":", 1)
                        if len(parts) == 2:
                            version = parts[1].strip()
                            if version:
                                return version
                    # Try next sibling
                    next_el = el.next
                    if next_el and next_el.tag:
                        version = next_el.text(strip=True)
                        if version:
                            return version

        return None

    def _extract_downloads(self, tree: HTMLParser) -> int | None:
        """Extract download count from stats area."""
        text = self._extract_first_text(
            tree,
            (
                "[data-role='downloads']",
                ".cFile_downloads",
                "[itemprop='interactionStatistic']",
            ),
        )
        if text:
            return self._parse_int(text)

        full = self._scan_labeled_text(
            tree,
            lambda value: ("download" in value) or ("total" in value),
        )
        if full:
            return self._parse_int(full)

        return None

    def _extract_file_size(self, tree: HTMLParser) -> str | None:
        """Extract file size display string from the page."""
        size = self._extract_first_text(
            tree,
            (
                "[data-role='fileSize']",
                ".cFile_size",
                "[itemprop='fileSize']",
            ),
        )
        if size:
            return size

        full = self._scan_labeled_text(
            tree,
            lambda value: ("size" in value)
            or ("mb" in value)
            or ("kb" in value)
            or ("gb" in value),
        )
        if full and len(full) < 60:
            return full

        return None

    def _extract_images(self, tree: HTMLParser) -> list[str]:
        """Extract image URLs from the gallery/screenshots area."""
        images: list[str] = []

        # Primary image selectors
        for selector in (
            ".ipsImage",
            ".cGalleryImage img",
            "[data-role='screenshot'] img",
            ".ipsThumb img",
            "[data-role='filePrimaryThumb'] img",
        ):
            for img in tree.css(selector):
                src = (
                    img.attributes.get("src")
                    or img.attributes.get("data-src")
                    or ""
                )
                if not src and img.attributes.get("srcset"):
                    srcset = img.attributes.get("srcset", "")
                    src = srcset.split(",")[0].strip().split(" ")[0]
                if src and src.startswith("http") and src not in images:
                    images.append(src)

        return images

    def _extract_updated_at(self, tree: HTMLParser) -> str | None:
        """Extract update timestamp from the page."""
        # Try time element first
        for selector in ("time", "[datetime]", "[data-role='updatedDate']"):
            el = tree.css_first(selector)
            if el:
                dt = el.attributes.get("datetime")
                if dt:
                    return dt
                title = el.attributes.get("title")
                if title:
                    return title
                text = el.text(strip=True)
                if text:
                    return text

        # Scan for "Updated" label
        for selector in ("li", "dt", "span", "div"):
            elements = tree.css(selector)
            for el in elements:
                text = el.text(strip=True).lower()
                if "updated" in text or "modified" in text:
                    parent = el.parent
                    if parent:
                        full = parent.text(strip=True)
                        parts = full.split(":", 1)
                        if len(parts) == 2:
                            return parts[1].strip()
                        return full

        return None

    def _extract_changelog(self, tree: HTMLParser) -> str | None:
        """Extract changelog section from the page."""
        for selector in (
            "[data-role='changelog']",
            ".cFile_changelog",
            ".ipsSpoiler_contents [data-role='content']",
        ):
            el = tree.css_first(selector)
            if el:
                text = el.text(strip=True)
                if text:
                    return text

        # Look for changelog heading and collect content after it
        headings = tree.css("h2, h3, h4, .ipsType_sectionHead")
        for heading in headings:
            text = heading.text(strip=True).lower()
            if "change" in text and "log" in text:
                # Walk forward siblings of the heading to find content
                node = heading.next
                max_siblings = 5
                while node and max_siblings > 0:
                    if node.tag:
                        role = node.attributes.get("data-role", "")
                        if role in ("content", "changelog"):
                            return node.text(strip=True)
                        content_el = node.css_first(
                            "[data-role='content'], .ipsType_richText"
                        )
                        if content_el:
                            return content_el.text(strip=True)
                        node_text = node.text(strip=True)
                        if node_text and len(node_text) > 10:
                            return node_text
                    node = node.next
                    max_siblings -= 1

        return None

    @staticmethod
    def _parse_int(text: str) -> int | None:
        """Extract the first integer from a text string.

        Handles formatted numbers like '1,234' and '3.5k'.
        """
        import re

        text = text.replace(",", "").strip()

        if "k" in text.lower():
            m = re.search(r"([\d.]+)\s*k", text, re.IGNORECASE)
            if m:
                try:
                    val = float(m.group(1)) * 1000
                    return int(val)
                except ValueError:
                    pass

        m = re.search(r"(\d+)", text)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _extract_external_id_from_url(url: str) -> str | None:
        """从原始内容中提取目标字段。"""
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if host and host not in ALLOWED_HOSTS:
            return None
        matched = re.search(r"^/files/file/(\d+)(?:[-/]|$)", parsed.path)
        if not matched:
            return None
        return matched.group(1)

    @staticmethod
    def _extract_file_id_from_external_id(external_id: str) -> str:
        value = str(external_id or "").strip()
        matched = re.fullmatch(r"[a-z0-9][a-z0-9_-]*:(\d+)", value, flags=re.IGNORECASE)
        if matched:
            return matched.group(1)
        return value

    @classmethod
    def _validate_loverslab_url(cls, url: str) -> str:
        """校验内部输入是否符合业务约束。"""
        normalized = (url or "").strip()
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("LoversLab page URL must be an absolute http(s) URL")
        if not cls._is_allowed_loverslab_url(normalized):
            raise ValueError(f"LoversLab page URL host is not allowed: {normalized}")
        return normalized

    @staticmethod
    def _is_allowed_loverslab_url(url: str) -> bool:
        """判断内部条件是否成立。"""
        host = (urlsplit(url).hostname or "").lower()
        return host in ALLOWED_HOSTS

    @staticmethod
    def _is_cloudflare_challenge_html(html: str) -> bool:
        """判断内部条件是否成立。"""
        lowered = html.lower()
        return (
            "just a moment..." in lowered
            and "challenges.cloudflare.com" in lowered
        ) or (
            "__cf_chl_" in lowered and "enable javascript and cookies to continue" in lowered
        )

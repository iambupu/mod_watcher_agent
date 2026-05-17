import asyncio
import calendar
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import feedparser

from app.adapters.base import BaseAdapter
from app.models.mod_item import ModItem
from app.schemas.watch_rule import LoversLabRuleConfig

logger = logging.getLogger(__name__)

FEED_URL = "https://www.loverslab.com/files/rss/"


class LoversLabFeedAdapter(BaseAdapter):
    """Adapter for LoversLab RSS/Atom feeds.

    Discovers mods by parsing LoversLab RSS feeds, optionally filtered
    by game tags specified in the watch rule.

    Note: this class is not auto-registered (source = None).
    Use LoversLabAdapter (source = "loverslab") for unified dispatch.
    """

    def __init__(self, **kwargs):
        pass

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        """Fetch and parse LoversLab RSS feed for new mods.

        Parses source_config_json as LoversLabRuleConfig.
        and fetches from the configured feedUrls. Falls back to the general feed
        if no feedUrls are configured.

        Args:
            source_config_json: JSON string conforming to LoversLabRuleConfig.

        Returns:
            A list of normalized ModItem objects.
        """
        config = LoversLabRuleConfig.model_validate_json(source_config_json)

        urls_to_fetch: list[str] = list(config.feedUrls)
        if not urls_to_fetch:
            urls_to_fetch.append(FEED_URL)

        all_results: list[ModItem] = []
        for url in urls_to_fetch:
            feed = await asyncio.to_thread(feedparser.parse, url)
            for entry in feed.entries:
                raw = self._normalize_entry(entry, config)
                if raw:
                    all_results.append(self.normalize(raw))

        return all_results

    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> ModItem | None:
        """Fetch a single mod's detail by external_id.

        V0.5: RSS feed already provides enough metadata for discovery.
        V0.6 will add page scraping for missing fields (version, downloads, etc.).

        Returns:
            None — not yet implemented.
        """
        return None

    def normalize(self, raw_item: dict) -> ModItem:
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
            updated_at=raw_item.get("updated_at_remote"),
            is_adult=raw_item.get("adult_content", False),
            raw=raw_item,
        )

    def _normalize_entry(self, entry, config: LoversLabRuleConfig) -> dict | None:
        """Convert a feedparser entry to a standardized mod dict.

        Extracts external_id from the entry link pattern /files/file/XXXXX/.

        Args:
            entry: A feedparser entry dict.
            config: The parsed LoversLabRuleConfig providing gameLabel.

        Returns:
            A normalized mod dict, or None if the entry link is invalid.
        """
        link = entry.get("link", "")
        m = re.search(r"/files/file/(\d+)", link)
        if not m:
            return None
        external_id = m.group(1)

        return {
            "source": "loverslab",
            "external_id": external_id,
            "game": config.gameLabel,
            "game_domain": None,
            "title": (entry.get("title", "") or "")[:512],
            "url": link,
            "author": entry.get("author", None),
            "category": (
                entry.get("tags", [{}])[0].get("term")
                if entry.get("tags")
                else None
            ),
            "tags_json": "[]",
            "original_summary": entry.get("summary", None),
            "version": None,
            "created_at_remote": None,
            "updated_at_remote": None,
            "published_at_remote": self._parse_published(entry),
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

    @staticmethod
    def _parse_published(entry) -> str | None:
        """Parse the published_parsed field from a feedparser entry.

        feedparser provides published_parsed as a time.struct_time tuple.
        Converts to UTC ISO-8601 string.

        Args:
            entry: A feedparser entry dict.

        Returns:
            ISO-8601 datetime string, or None if not available.
        """
        published_parsed = entry.get("published_parsed")
        if published_parsed:
            dt = datetime.fromtimestamp(
                calendar.timegm(published_parsed), tz=timezone.utc
            )
            return dt.isoformat()
        return None

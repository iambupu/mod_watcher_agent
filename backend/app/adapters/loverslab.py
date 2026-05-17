"""Unified LoversLab adapter — dispatches to feed / page sub-adapters.

Registered as source "loverslab" in BaseAdapter.adapters.
For "both" mode, results are merged and deduplicated by external_id.
"""

import logging
from typing import Any

from app.adapters.base import BaseAdapter
from app.adapters.loverslab_feed import LoversLabFeedAdapter
from app.adapters.loverslab_page import LoversLabPageAdapter
from app.models.mod_item import ModItem
from app.schemas.watch_rule import LoversLabRuleConfig

logger = logging.getLogger(__name__)


class LoversLabAdapter(BaseAdapter):
    """Unified adapter for LoversLab — delegates to feed and/or page scraping."""

    source = "loverslab"

    def __init__(self, **kwargs: Any) -> None:
        self._feed = LoversLabFeedAdapter()
        self._page = LoversLabPageAdapter()

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        config = LoversLabRuleConfig.model_validate_json(source_config_json)
        results: list[ModItem] = []

        if config.accessMode in ("rss", "both"):
            feed_results = await self._feed.fetch(source_config_json)
            results.extend(feed_results)

        if config.accessMode in ("page", "both"):
            page_results = await self._page.fetch(source_config_json)
            results.extend(page_results)

        if config.accessMode == "both":
            seen: set[str] = set()
            deduped: list[ModItem] = []
            for item in results:
                if item.source_id not in seen:
                    seen.add(item.source_id)
                    deduped.append(item)
            return deduped

        return results

    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> ModItem | None:
        return await self._page.fetch_mod_detail(external_id, game_domain)

    def normalize(self, raw_item: dict) -> ModItem:
        return self._page.normalize(raw_item)

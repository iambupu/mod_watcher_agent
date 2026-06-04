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
        """初始化实例并保存运行所需的依赖。"""
        _ = kwargs
        self._feed = LoversLabFeedAdapter()
        self._page = LoversLabPageAdapter()

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        """请求外部数据并返回标准化结果。"""
        config = LoversLabRuleConfig.model_validate_json(source_config_json)
        results: list[ModItem] = []

        if config.accessMode in ("rss", "both"):
            feed_results = await self._feed.fetch(source_config_json)
            results.extend(feed_results)

        if config.accessMode in ("page", "both"):
            page_results = await self._page.fetch(source_config_json)
            results.extend(page_results)

        if config.accessMode == "both":
            seen: dict[str, ModItem] = {}
            for item in results:
                existing = seen.get(item.source_id)
                if existing is None or _is_newer_loverslab_item(item, existing):
                    seen[item.source_id] = item
            return list(seen.values())

        return results

    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> ModItem | None:
        """请求外部数据并返回标准化结果。"""
        return await self._page.fetch_mod_detail(external_id, game_domain)

    async def aclose(self) -> None:
        """Close pooled resources held by feed/page sub-adapters."""
        await self._feed.aclose()
        await self._page.aclose()

    def normalize(self, raw_item: dict) -> ModItem:
        """规范化输入数据，供后续流程使用。"""
        return self._page.normalize(raw_item)


def _is_newer_loverslab_item(candidate: ModItem, existing: ModItem) -> bool:
    if candidate.updated_at is None:
        return False
    if existing.updated_at is None:
        return True
    return candidate.updated_at > existing.updated_at

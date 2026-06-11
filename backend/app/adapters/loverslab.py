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
        """组合 RSS 和页面抓取子适配器，统一对外暴露 loverslab 来源。"""
        _ = kwargs
        self._feed = LoversLabFeedAdapter()
        self._page = LoversLabPageAdapter()

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        """按规则 accessMode 执行 RSS、页面抓取或两者合并。"""
        config = LoversLabRuleConfig.model_validate_json(source_config_json)
        results: list[ModItem] = []

        if config.accessMode in ("rss", "both"):
            feed_results = await self._feed.fetch(source_config_json)
            results.extend(feed_results)

        if config.accessMode in ("page", "both"):
            page_results = await self._page.fetch(source_config_json)
            results.extend(page_results)

        if config.accessMode == "both":
            # 同一个文件可能同时来自 RSS 和页面列表；保留更新时间更新的一条。
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
        """详情页只有页面适配器能补齐，因此直接委托给 page 子适配器。"""
        return await self._page.fetch_mod_detail(external_id, game_domain)

    async def aclose(self) -> None:
        """Close pooled resources held by feed/page sub-adapters."""
        await self._feed.aclose()
        await self._page.aclose()

    def normalize(self, raw_item: dict) -> ModItem:
        """复用页面适配器的 LoversLab 字段规范化逻辑。"""
        return self._page.normalize(raw_item)


def _is_newer_loverslab_item(candidate: ModItem, existing: ModItem) -> bool:
    if candidate.updated_at is None:
        return False
    if existing.updated_at is None:
        return True
    return candidate.updated_at > existing.updated_at

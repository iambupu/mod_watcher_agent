"""LoversLab RSS adapter registered for unified source dispatch."""

from typing import Any

from app.adapters.base import BaseAdapter
from app.adapters.loverslab_feed import LoversLabFeedAdapter
from app.models.mod_item import ModItem


class LoversLabAdapter(BaseAdapter):
    """Expose RSS-based LoversLab discovery through the shared adapter API."""

    source = "loverslab"

    def __init__(self, **kwargs: Any) -> None:
        """创建 RSS 子适配器并复用其连接池。"""
        _ = kwargs
        self._feed = LoversLabFeedAdapter()

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        """通过配置的 RSS Feed 发现 LoversLab 条目。"""
        return await self._feed.fetch(source_config_json)

    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> ModItem | None:
        """RSS 来源不执行网页详情抓取。"""
        return await self._feed.fetch_mod_detail(external_id, game_domain)

    async def aclose(self) -> None:
        """关闭 RSS 适配器持有的 HTTP 连接池。"""
        await self._feed.aclose()

    def normalize(self, raw_item: dict) -> ModItem:
        """复用 RSS 适配器的 LoversLab 字段规范化逻辑。"""
        return self._feed.normalize(raw_item)

import pytest

from app.adapters.loverslab import LoversLabAdapter
from app.models.mod_item import ModItem
from app.schemas.watch_rule import LoversLabRuleConfig


class _FakeFeedAdapter:
    def __init__(self, items: list[ModItem]) -> None:
        self.items = items
        self.closed = False

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        LoversLabRuleConfig.model_validate_json(source_config_json)
        return self.items

    async def fetch_mod_detail(
        self,
        external_id: str,
        game_domain: str | None = None,
    ) -> None:
        _ = (external_id, game_domain)
        return None

    async def aclose(self) -> None:
        self.closed = True

    def normalize(self, raw_item: dict) -> ModItem:
        return raw_item["item"]


def _config_json() -> str:
    return LoversLabRuleConfig(
        gameLabel="Skyrim SE",
        feedUrls=["https://www.loverslab.com/files/rss/1-skyrim-se.xml/"],
        maxItemsPerRun=20,
    ).model_dump_json()


@pytest.mark.asyncio
async def test_fetch_delegates_to_rss_adapter():
    item = ModItem(
        source_id="1001",
        source="loverslab",
        name="Feed Title",
        game="Skyrim SE",
        url="https://www.loverslab.com/files/file/1001-feed-title/",
    )
    adapter = LoversLabAdapter()
    adapter._feed = _FakeFeedAdapter([item])

    assert await adapter.fetch(_config_json()) == [item]


@pytest.mark.asyncio
async def test_close_delegates_to_rss_adapter():
    feed = _FakeFeedAdapter([])
    adapter = LoversLabAdapter()
    adapter._feed = feed

    await adapter.aclose()

    assert feed.closed is True

from datetime import UTC, datetime

import pytest

from app.adapters.loverslab import LoversLabAdapter
from app.models.mod_item import ModItem
from app.schemas.watch_rule import LoversLabRuleConfig


class _FakeSourceAdapter:
    def __init__(self, items):
        self._items = items

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        return self._items


def _config_json() -> str:
    return LoversLabRuleConfig(
        gameLabel="Skyrim SE",
        accessMode="both",
        feedUrls=["https://www.loverslab.com/files/rss/1-skyrim-se.xml/"],
        pageUrls=["https://www.loverslab.com/files/category/110-skyrim/"],
        maxItemsPerRun=20,
    ).model_dump_json()


def _item(source_id: str, title: str, updated_at: datetime | None) -> ModItem:
    return ModItem(
        source_id=source_id,
        source="loverslab",
        name=title,
        game="Skyrim SE",
        url=f"https://www.loverslab.com/files/file/{source_id}-{title}/",
        updated_at=updated_at,
    )


@pytest.mark.asyncio
async def test_both_mode_deduplicates_by_keeping_newer_item():
    adapter = LoversLabAdapter()
    adapter._feed = _FakeSourceAdapter([
        _item("1001", "Old Feed Title", datetime(2025, 1, 1, tzinfo=UTC)),
    ])
    adapter._page = _FakeSourceAdapter([
        _item("1001", "New Page Title", datetime(2025, 2, 1, tzinfo=UTC)),
    ])

    results = await adapter.fetch(_config_json())

    assert len(results) == 1
    assert results[0].name == "New Page Title"

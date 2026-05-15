"""Tests for NexusModsAdapter single-source mode."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.nexusmods import RateLimitError

FAKE_GAME_DOMAIN = "skyrimspecialedition"
FAKE_MOD_ID = 12345


def _valid_config_json(game_domain=FAKE_GAME_DOMAIN):
    return json.dumps({
        "gameDomainName": game_domain,
        "updatedSinceDays": 30,
        "queryMode": "updated",
        "categoryNames": [],
        "tags": [],
        "sortBy": "updatedAt_desc",
    })


def _make_mod_node(
    mod_id=FAKE_MOD_ID,
    name="Test Mod",
    summary="A test mod.",
    author_name="TestAuthor",
    category_name="Weapons",
    game_domain=FAKE_GAME_DOMAIN,
    game_name="Skyrim Special Edition",
    version="1.0.0",
    downloads=1000,
    unique_downloads=800,
    endorsements=50,
    views=5000,
):
    return {
        "uid": str(1704 * 4294967296 + mod_id),
        "modId": mod_id,
        "name": name,
        "summary": summary,
        "author": author_name,
        "category": category_name,
        "game": {"domainName": game_domain, "name": game_name},
        "gameId": 1704,
        "version": version,
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2025-06-01T12:00:00Z",
        "downloads": downloads,
        "endorsements": endorsements,
        "adultContent": False,
        "thumbnailUrl": "https://example.com/thumb.jpg",
        "tags": [{"name": "Weapons"}],
    }


@pytest.fixture
def adapter():
    from app.adapters.nexusmods import NexusModsAdapter

    return NexusModsAdapter(api_key="test_key")


def _mock_query_result(adapter, return_value):
    adapter._graphql_query = AsyncMock(return_value=return_value)


class TestNexusModsAdapter:
    @pytest.mark.asyncio
    async def test_fetch_returns_mod_items(self, adapter):
        node = _make_mod_node()
        payload = {
            "data": {
                "mods": {
                    "nodes": [node],
                    "nodesCount": 1,
                    "totalCount": 1,
                }
            }
        }
        _mock_query_result(adapter, payload)

        results = await adapter.fetch(_valid_config_json())

        assert len(results) == 1
        assert isinstance(results[0], type(adapter.normalize({})))
        mod = results[0]
        assert mod.source_id == str(FAKE_MOD_ID)
        assert mod.source == "nexusmods"
        assert mod.name == "Test Mod"
        assert mod.game == "Skyrim Special Edition"
        assert mod.url == f"https://www.nexusmods.com/{FAKE_GAME_DOMAIN}/mods/{FAKE_MOD_ID}"
        assert mod.author == "TestAuthor"
        assert mod.categories == ["Weapons"]
        assert mod.summary == "A test mod."
        assert mod.downloads == 1000
        assert mod.endorsements == 50
        assert mod.thumbnail_url == "https://example.com/thumb.jpg"
        assert mod.is_adult is False
        assert mod.updated_at == datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

    def test_normalize_maps_fields(self, adapter):
        node = _make_mod_node()

        mod = adapter.normalize(node)

        assert mod.source_id == str(FAKE_MOD_ID)
        assert mod.source == "nexusmods"
        assert mod.name == "Test Mod"
        assert mod.game == "Skyrim Special Edition"
        assert mod.url == f"https://www.nexusmods.com/{FAKE_GAME_DOMAIN}/mods/{FAKE_MOD_ID}"
        assert mod.summary == "A test mod."
        assert mod.author == "TestAuthor"
        assert mod.downloads == 1000
        assert mod.endorsements == 50
        assert mod.likes == 0
        assert mod.categories == ["Weapons"]
        assert mod.tags == ["Weapons"]
        assert mod.thumbnail_url == "https://example.com/thumb.jpg"
        assert mod.updated_at == datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        assert mod.is_adult is False
        assert mod.raw is node

    def test_default_values_applied(self, adapter):
        minimal_node = {
            "uid": "1",
            "modId": 1,
            "name": "",
            "summary": "",
            "author": "",
            "category": "",
            "game": {},
            "gameId": None,
            "version": "",
            "createdAt": None,
            "updatedAt": None,
            "downloads": 0,
            "endorsements": 0,
            "adultContent": False,
            "thumbnailUrl": "",
            "tags": [],
        }

        mod = adapter.normalize(minimal_node)

        assert mod.source_id == "1"
        assert mod.source == "nexusmods"
        assert mod.name == ""
        assert mod.game == ""
        assert mod.summary == ""
        assert mod.author == ""
        assert mod.downloads == 0
        assert mod.endorsements == 0
        assert mod.likes == 0
        assert mod.categories == []
        assert mod.tags == []
        assert mod.thumbnail_url == ""
        assert mod.updated_at is None
        assert mod.is_adult is False

    def test_source_config_parsed(self, adapter):
        import app.adapters.nexusmods as nxmod

        orig = nxmod.NexusModsAdapter._graphql_query
        nxmod.NexusModsAdapter._graphql_query = AsyncMock(return_value={
            "data": {
                "mods": {
                    "nodes": [],
                    "nodesCount": 0,
                    "totalCount": 0,
                }
            }
        })

        config_json = json.dumps({
            "gameDomainName": "fallout4",
            "updatedSinceDays": 7,
            "queryMode": "created",
            "categoryNames": ["Armour"],
            "tags": ["lore-friendly"],
            "sortBy": "downloads_desc",
        })

        async def _run():
            return await adapter.fetch(config_json)

        import asyncio
        results = asyncio.run(_run())
        assert results == []

        nxmod.NexusModsAdapter._graphql_query = orig

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self, adapter):
        payload = {
            "data": {
                "mods": {
                    "nodes": [],
                    "nodesCount": 0,
                    "totalCount": 0,
                }
            }
        }
        _mock_query_result(adapter, payload)

        results = await adapter.fetch(_valid_config_json())

        assert results == []
        assert isinstance(results, list)

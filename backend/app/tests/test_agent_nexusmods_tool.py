from unittest.mock import AsyncMock

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.adapters.nexusmods import NexusModsAdapter
from app.models.mod import Mod
from app.services.agent.tools.nexusmods_search_tool import (
    NexusModsSearchInput,
    NexusModsSearchTool,
    nexus_tool_input_from_plan,
)
from app.services.settings_service import SettingsService


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _node(mod_id=9001, name="Hot Armor Pack", downloads=1200, endorsements=80):
    return {
        "uid": str(mod_id),
        "modId": mod_id,
        "name": name,
        "summary": "A flexible armor gameplay mod.",
        "author": "Author",
        "category": "Armour",
        "game": {"domainName": "skyrimspecialedition", "name": "Skyrim Special Edition"},
        "gameId": 1704,
        "version": "1.0",
        "createdAt": "2026-05-01T00:00:00Z",
        "updatedAt": "2026-05-20T00:00:00Z",
        "downloads": downloads,
        "endorsements": endorsements,
        "adultContent": False,
        "thumbnailUrl": "https://example.com/thumb.jpg",
        "tags": [{"name": "Armour"}],
    }


def _clothing_node(mod_id=9002, name="Elegant Female Outfit"):
    node = _node(mod_id=mod_id, name=name, downloads=500, endorsements=20)
    node["summary"] = "A CBBE dress and outfit for female characters."
    node["category"] = "Clothing and Accessories"
    node["tags"] = [{"name": "Clothing"}]
    return node


@pytest.mark.asyncio
async def test_nexusmods_search_tool_builds_graphql_filter_and_persists_results(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    captured = {}

    async def fake_graphql(self, query, variables):
        captured["query"] = query
        captured["variables"] = variables
        return {
            "data": {
                "mods": {
                    "nodes": [_node()],
                    "nodesCount": 1,
                    "totalCount": 1,
                }
            }
        }

    monkeypatch.setattr(NexusModsAdapter, "_graphql_query", fake_graphql)
    with Session(engine) as session:
        SettingsService(session).set("nexus_api_key", "test-key")
        tool = NexusModsSearchTool(session)
        results = await tool.run(
            NexusModsSearchInput(
                query="hot armor",
                game_domain="skyrimspecialedition",
                categories=["Armour"],
                adult_content=False,
                min_downloads=100,
                sort_field="downloads",
                limit=8,
            )
        )

        persisted = session.exec(select(Mod).where(Mod.source == "nexusmods", Mod.external_id == "9001")).first()

    assert len(results) == 1
    assert results[0].tool_name == "nexusmods_search"
    assert results[0].mod.title == "Hot Armor Pack"
    assert results[0].score >= 1
    assert persisted is not None
    assert persisted.title == "Hot Armor Pack"
    assert captured["variables"]["sort"] == [{"downloads": {"direction": "DESC"}}]
    graphql_filter = captured["variables"]["filter"]
    assert graphql_filter["op"] == "AND"
    assert {"gameDomainName": [{"op": "EQUALS", "value": "skyrimspecialedition"}]} in graphql_filter["filter"]
    assert {"categoryName": [{"op": "EQUALS", "value": "Armour"}]} in graphql_filter["filter"]
    assert {"adultContent": [{"op": "EQUALS", "value": False}]} in graphql_filter["filter"]
    assert {"downloads": [{"op": "GTE", "value": 100}]} in graphql_filter["filter"]


@pytest.mark.asyncio
async def test_nexusmods_search_tool_returns_empty_without_api_key(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    mocked = AsyncMock()
    monkeypatch.setattr(NexusModsAdapter, "_graphql_query", mocked)

    with Session(engine) as session:
        results = await NexusModsSearchTool(session).run(
            NexusModsSearchInput(query="armor", game_domain="skyrimspecialedition")
        )

    assert results == []
    mocked.assert_not_called()


def test_nexus_tool_input_respects_source_and_game_domain_plan():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        plan = {
            "sources": ["nexusmods"],
            "game_domains": ["skyrimspecialedition"],
            "categories": ["Armour"],
            "adult_content": True,
            "sort_field": "endorsements",
            "sort_order": "desc",
            "limit": 5,
        }

        tool_input = nexus_tool_input_from_plan(session, "热门成人护甲 Mod", plan)

    assert tool_input is not None
    assert tool_input.game_domain == "skyrimspecialedition"
    assert tool_input.categories == ["Armour"]
    assert tool_input.adult_content is True
    assert tool_input.sort_field == "endorsements"
    assert tool_input.limit == 5


@pytest.mark.asyncio
async def test_nexusmods_search_tool_expands_chinese_female_clothing_query(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    captured = {}

    async def fake_graphql(self, query, variables):
        captured["variables"] = variables
        return {
            "data": {
                "mods": {
                    "nodes": [_clothing_node()],
                    "nodesCount": 1,
                    "totalCount": 1,
                }
            }
        }

    monkeypatch.setattr(NexusModsAdapter, "_graphql_query", fake_graphql)
    with Session(engine) as session:
        SettingsService(session).set("nexus_api_key", "test-key")
        results = await NexusModsSearchTool(session).run(
            NexusModsSearchInput(query="只看女性服装", game_domain="skyrimspecialedition", limit=8)
        )

    assert len(results) == 1
    assert results[0].tool_name == "nexusmods_search"
    graphql_filter = captured["variables"]["filter"]["filter"]
    assert {"categoryName": [{"op": "EQUALS", "value": "Clothing and Accessories"}]} in graphql_filter
    keyword_clause = next(item for item in graphql_filter if item.get("op") == "OR")
    keyword_values = {
        clause[field][0]["value"]
        for clause in keyword_clause["filter"]
        for field in ("nameStemmed", "description")
        if field in clause
    }
    assert "female" in keyword_values
    assert "outfit" in keyword_values


def test_nexus_tool_input_skips_non_nexus_source():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        assert nexus_tool_input_from_plan(session, "anything", {"sources": ["loverslab"]}) is None

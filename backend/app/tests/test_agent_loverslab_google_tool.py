import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.mod import Mod
from app.services.agent.tools.loverslab_google_search_tool import (
    LoversLabGoogleSearchInput,
    LoversLabGoogleSearchTool,
    loverslab_google_input_from_plan,
)
from app.services.settings_service import SettingsService


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.mark.asyncio
async def test_loverslab_google_tool_builds_site_restricted_query_and_persists_results(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    captured = {}

    async def fake_fetch(self, params):
        captured["params"] = params
        return {
            "items": [
                {
                    "title": "Follower Pack II by ZckeZckT SE - LoversLab",
                    "link": "https://www.loverslab.com/files/file/12345-follower-pack/",
                    "snippet": "Adds followers to your game.",
                    "pagemap": {"cse_thumbnail": [{"src": "https://example.com/thumb.jpg"}]},
                },
                {
                    "title": "External result",
                    "link": "https://example.com/not-loverslab",
                    "snippet": "ignored",
                },
            ]
        }

    monkeypatch.setattr(LoversLabGoogleSearchTool, "_fetch", fake_fetch)
    with Session(engine) as session:
        SettingsService(session).set("google_search_api_key", "google-key")
        SettingsService(session).set("google_search_engine_id", "cx-id")

        results = await LoversLabGoogleSearchTool(session).run(
            LoversLabGoogleSearchInput(query="follower pack", game="Skyrim Special Edition", limit=5)
        )
        persisted = session.exec(select(Mod).where(Mod.source == "loverslab")).all()

    assert captured["params"]["siteSearch"] == "loverslab.com"
    assert captured["params"]["siteSearchFilter"] == "i"
    assert captured["params"]["safe"] == "off"
    assert "site:" not in captured["params"]["q"]
    assert len(results) == 1
    assert results[0].tool_name == "loverslab_google_search"
    assert results[0].score >= 1
    assert len(persisted) == 1
    assert persisted[0].title == "Follower Pack II by ZckeZckT SE"
    assert persisted[0].game == "Skyrim Special Edition"
    assert persisted[0].thumbnail_url == "https://example.com/thumb.jpg"


@pytest.mark.asyncio
async def test_loverslab_google_tool_returns_empty_without_google_config(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    called = False

    async def fake_fetch(self, params):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(LoversLabGoogleSearchTool, "_fetch", fake_fetch)
    with Session(engine) as session:
        results = await LoversLabGoogleSearchTool(session).run(
            LoversLabGoogleSearchInput(query="armor", game="Skyrim Special Edition")
        )

    assert results == []
    assert called is False


def test_loverslab_google_input_respects_source_filter():
    assert loverslab_google_input_from_plan("armor", {"sources": ["nexusmods"]}) is None
    tool_input = loverslab_google_input_from_plan(
        "成人 follower mod",
        {"sources": ["loverslab"], "games": ["Skyrim Special Edition"], "limit": 6},
    )
    assert tool_input is not None
    assert tool_input.game == "Skyrim Special Edition"
    assert tool_input.adult_content is True
    assert tool_input.limit == 6


def test_loverslab_google_tool_expands_chinese_query_terms():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        tool = LoversLabGoogleSearchTool(session)
        params = tool._build_params(
            LoversLabGoogleSearchInput(query="只看女性服装", limit=5),
            "google-key",
            "cx-id",
        )

    assert "female" in str(params["q"])
    assert "outfit" in str(params["q"])

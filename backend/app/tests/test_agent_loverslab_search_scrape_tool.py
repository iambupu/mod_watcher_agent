import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.mod import Mod
from app.services.agent.tools.loverslab_search_scrape_tool import (
    LoversLabSearchScrapeInput,
    LoversLabSearchScrapeTool,
    loverslab_scrape_input_from_plan,
)
from app.services.settings_service import SettingsService


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.mark.asyncio
async def test_loverslab_search_scrape_tool_parses_duckduckgo_results_and_persists(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    captured = {}
    html = """
    <div class="result">
      <a class="result__a" href="/l/?uddg=https%3A%2F%2Fwww.loverslab.com%2Ffiles%2Ffile%2F12345-follower-pack%2F">Follower Pack II - LoversLab</a>
      <a class="result__snippet">Adds followers to your game.</a>
    </div>
    <div class="result">
      <a class="result__a" href="https://example.com/not-loverslab">External result</a>
    </div>
    """

    async def fake_fetch(self, *, query, engine, limit):
        captured["query"] = query
        captured["engine"] = engine
        captured["limit"] = limit
        return html

    monkeypatch.setattr(LoversLabSearchScrapeTool, "_fetch_search_page", fake_fetch)
    with Session(engine) as session:
        SettingsService(session).set("loverslab_search_scrape_engine", "duckduckgo")

        results = await LoversLabSearchScrapeTool(session).run(
            LoversLabSearchScrapeInput(query="follower pack", game="Skyrim Special Edition", limit=5)
        )
        persisted = session.exec(select(Mod).where(Mod.source == "loverslab")).all()

    assert captured["engine"] == "duckduckgo"
    assert "site:loverslab.com" in captured["query"]
    assert "follower pack" in captured["query"]
    assert len(results) == 1
    assert results[0].tool_name == "loverslab_scrape_search"
    assert results[0].score >= 1
    assert len(persisted) == 1
    assert persisted[0].title == "Follower Pack II"
    assert persisted[0].game == "Skyrim Special Edition"
    assert persisted[0].category == "Search Scrape (duckduckgo)"


@pytest.mark.asyncio
async def test_loverslab_search_scrape_tool_returns_empty_when_disabled(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    called = False

    async def fake_fetch(self, *, query, engine, limit):
        nonlocal called
        called = True
        return ""

    monkeypatch.setattr(LoversLabSearchScrapeTool, "_fetch_search_page", fake_fetch)
    with Session(engine) as session:
        SettingsService(session).set("loverslab_search_scrape_enabled", "false")
        results = await LoversLabSearchScrapeTool(session).run(LoversLabSearchScrapeInput(query="armor"))

    assert results == []
    assert called is False


def test_loverslab_scrape_input_reuses_loverslab_source_rules():
    assert loverslab_scrape_input_from_plan("armor", {"sources": ["nexusmods"]}) is None
    tool_input = loverslab_scrape_input_from_plan(
        "最近更新的 LoversLab follower mod",
        {"sources": ["loverslab"], "games": ["Skyrim Special Edition"], "limit": 6},
    )
    assert tool_input is not None
    assert tool_input.game == "Skyrim Special Edition"
    assert tool_input.limit == 6


def test_loverslab_search_scrape_query_uses_semantic_terms():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        query = LoversLabSearchScrapeTool(session)._build_query(
            LoversLabSearchScrapeInput(query="只看女性服装", game="Skyrim Special Edition")
        )

    assert "site:loverslab.com" in query
    assert "female" in query
    assert "outfit" in query

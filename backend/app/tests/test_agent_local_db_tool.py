import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.services.agent import mod_search_service
from app.services.agent.retrievers.sqlite_fts_retriever import SqliteFtsResult
from app.services.agent.search_types import SearchPlan
from app.services.agent.tools.local_db_search_tool import LocalDbSearchInput, LocalDbSearchTool


def _engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.mark.asyncio
async def test_local_db_tool_returns_search_results():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="1",
                game="Stellar Blade",
                title="XXTB Suit",
                url="https://example.com/1",
                first_seen_at="2026-05-20T00:00:00+00:00",
                last_seen_at="2026-05-20T00:00:00+00:00",
            )
        )
        session.commit()

        plan = SearchPlan.from_query_plan({"keywords": ["XXTB"], "limit": 8})
        results = await LocalDbSearchTool(session).run(LocalDbSearchInput(query="XXTB的mod", plan=plan))

    assert results
    assert results[0].tool_name == "local_db_search"
    assert results[0].mod.title == "XXTB Suit"
    assert results[0].score >= 1


@pytest.mark.asyncio
async def test_local_db_tool_uses_sqlite_fts_for_relevance_keywords(monkeypatch):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mod = Mod(
            source="nexusmods",
            external_id="1",
            game="Stellar Blade",
            title="Ocean String",
            url="https://example.com/1",
            first_seen_at="2026-05-20T00:00:00+00:00",
            last_seen_at="2026-05-20T00:00:00+00:00",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        seen = {}

        def fake_query_mods_fts(session_arg, *, keywords, filters, limit):
            seen["keywords"] = keywords
            seen["filters"] = filters
            seen["limit"] = limit
            return [SqliteFtsResult(mod=mod, score=77)]

        monkeypatch.setattr(mod_search_service, "query_mods_fts", fake_query_mods_fts)

        plan = SearchPlan.from_query_plan({"keywords": ["成人服装"], "sort_field": "relevance", "limit": 8})
        results = await LocalDbSearchTool(session).run(LocalDbSearchInput(query="成人服装", plan=plan))

    assert seen["keywords"] == ["成人服装"]
    assert seen["filters"]["sort_field"] == "relevance"
    assert seen["limit"] == 8
    assert results[0].score == 77
    assert results[0].mod.title == "Ocean String"

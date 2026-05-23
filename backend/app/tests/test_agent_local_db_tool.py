import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
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

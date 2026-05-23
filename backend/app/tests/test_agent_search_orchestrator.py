import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.services.agent.search_orchestrator import AgentSearchOrchestrator
from app.services.agent.search_types import SearchResult


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.mark.asyncio
async def test_find_matches_queries_nexus_when_source_is_explicit(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    called = False

    async def fake_run(self, tool_input):  # noqa: ARG001
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("app.services.agent.search_orchestrator.NexusModsSearchTool.run", fake_run)

    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="local-xxtb",
                game="Stellar Blade",
                game_domain="stellarblade",
                title="XXTB - Prototype Suit CNS",
                url="https://example.com/local-xxtb",
                first_seen_at="2026-05-20T00:00:00+00:00",
                last_seen_at="2026-05-20T00:00:00+00:00",
            )
        )
        session.commit()

        matches = await AgentSearchOrchestrator(session).find_matches(
            query="XXTB的mod",
            query_plan={
                "keywords": ["XXTB"],
                "games": ["Stellar Blade"],
                "game_domains": [],
                "categories": [],
                "sources": ["nexusmods"],
                "adult_content": None,
                "sort_field": "updated_at_remote",
                "sort_order": "desc",
                "limit": 8,
            },
            llm_available=False,
            provider="ollama",
            api_key="",
            base_url="",
            model="qwen3:8b",
        )

    assert called is True
    assert [match.title for match in matches] == ["XXTB - Prototype Suit CNS"]


@pytest.mark.asyncio
async def test_find_matches_queries_nexus_for_distinctive_term_and_infers_game(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    seen_game_domain = None

    async def fake_run(self, tool_input):  # noqa: ARG001
        nonlocal seen_game_domain
        seen_game_domain = tool_input.game_domain
        online = Mod(
            source="nexusmods",
            external_id="online-xxtb",
            game="Stellar Blade",
            game_domain="stellarblade",
            title="XXTB-Overhaul Cybernetic Dress-Suit",
            url="https://example.com/online-xxtb",
            first_seen_at="2026-05-21T00:00:00+00:00",
            last_seen_at="2026-05-21T00:00:00+00:00",
        )
        self.session.add(online)
        self.session.flush()
        return [SearchResult(score=9, mod=online, tool_name="nexusmods_search")]

    monkeypatch.setattr("app.services.agent.search_orchestrator.NexusModsSearchTool.run", fake_run)

    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="local-xxtb",
                game="Stellar Blade",
                game_domain="stellarblade",
                title="XXTB - Prototype Suit CNS",
                url="https://example.com/local-xxtb",
                first_seen_at="2026-05-20T00:00:00+00:00",
                last_seen_at="2026-05-20T00:00:00+00:00",
            )
        )
        session.commit()

        matches = await AgentSearchOrchestrator(session).find_matches(
            query="XXTB的mod",
            query_plan={
                "keywords": [],
                "games": [],
                "game_domains": [],
                "categories": [],
                "sources": [],
                "adult_content": None,
                "sort_field": "updated_at_remote",
                "sort_order": "desc",
                "limit": 8,
            },
            llm_available=False,
            provider="ollama",
            api_key="",
            base_url="",
            model="qwen3:8b",
        )

    assert seen_game_domain == "stellarblade"
    assert [match.title for match in matches] == [
        "XXTB-Overhaul Cybernetic Dress-Suit",
        "XXTB - Prototype Suit CNS",
    ]


@pytest.mark.asyncio
async def test_find_matches_filters_online_results_by_distinctive_query_term(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    async def fake_run(self, tool_input):  # noqa: ARG001
        unrelated = Mod(
            source="nexusmods",
            external_id="online-kawaii",
            game="Stellar Blade",
            game_domain="stellarblade",
            title="Kawaii War Dress TypeA (CNS Compatible)",
            url="https://example.com/online-kawaii",
            first_seen_at="2026-05-21T00:00:00+00:00",
            last_seen_at="2026-05-21T00:00:00+00:00",
        )
        self.session.add(unrelated)
        self.session.flush()
        return [SearchResult(score=99, mod=unrelated, tool_name="nexusmods_search")]

    monkeypatch.setattr("app.services.agent.search_orchestrator.NexusModsSearchTool.run", fake_run)

    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="local-xxtb",
                game="Stellar Blade",
                game_domain="stellarblade",
                title="XXTB - Prototype Suit CNS",
                url="https://example.com/local-xxtb",
                first_seen_at="2026-05-20T00:00:00+00:00",
                last_seen_at="2026-05-20T00:00:00+00:00",
            )
        )
        session.commit()

        matches = await AgentSearchOrchestrator(session).find_matches(
            query="XXTB的mod",
            query_plan={
                "keywords": ["XXTB"],
                "games": ["Stellar Blade"],
                "game_domains": [],
                "categories": [],
                "sources": ["nexusmods"],
                "adult_content": None,
                "sort_field": "relevance",
                "sort_order": "desc",
                "limit": 8,
            },
            llm_available=False,
            provider="ollama",
            api_key="",
            base_url="",
            model="qwen3:8b",
        )

    assert [match.title for match in matches] == ["XXTB - Prototype Suit CNS"]

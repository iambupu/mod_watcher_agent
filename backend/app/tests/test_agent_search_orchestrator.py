import logging

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.services.agent.search_orchestrator import AgentSearchOrchestrator
from app.services.agent.search_types import SearchResult
from app.services.agent.tools.loverslab_google_search_tool import LoversLabGoogleSearchTool
from app.services.agent.tools.loverslab_search_scrape_tool import LoversLabSearchScrapeTool
from app.services.agent.tools.nexusmods_search_tool import NexusModsSearchTool
from app.services.agent.tools.web_search_tool import WebSearchOutput


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

    async def fake_run(self, query, query_plan, evidence_id=None, conservative_mode=False):  # noqa: ARG001
        nonlocal called
        called = True
        return WebSearchOutput(results=[], evidence=[])

    monkeypatch.setattr("app.services.agent.search_orchestrator.WebSearchTool.run", fake_run)

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

    async def fake_run(self, query, query_plan, evidence_id=None, conservative_mode=False):  # noqa: ARG001
        nonlocal seen_game_domain
        seen_game_domain = (query_plan.get("game_domains") or [None])[0]
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
        return WebSearchOutput(
            results=[SearchResult(score=9, mod=online, tool_name="nexusmods_search")],
            evidence=[],
        )

    monkeypatch.setattr("app.services.agent.search_orchestrator.WebSearchTool.run", fake_run)

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
async def test_find_matches_uses_web_search_tool_boundary_for_online_retrieval(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    called = False

    async def fake_web_search_run(self, query, query_plan, evidence_id=None, conservative_mode=False):  # noqa: ARG001
        nonlocal called
        called = True
        online = Mod(
            source="nexusmods",
            external_id="online-boundary",
            game="Stellar Blade",
            game_domain="stellarblade",
            title="XXTB Boundary Online Result",
            url="https://example.com/online-boundary",
            first_seen_at="2026-05-21T00:00:00+00:00",
            last_seen_at="2026-05-21T00:00:00+00:00",
        )
        self.session.add(online)
        self.session.flush()
        return WebSearchOutput(
            results=[SearchResult(score=9, mod=online, tool_name="web_search")],
            evidence=[
                {
                    "fragment_id": "r_web_boundary",
                    "stage": "online_retrieval",
                    "tool": "web_search",
                    "status": "succeeded",
                    "count": 1,
                }
            ],
        )

    async def fail_leaf_tool(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("leaf online tools must stay behind WebSearchTool")

    monkeypatch.setattr("app.services.agent.search_orchestrator.WebSearchTool.run", fake_web_search_run)
    monkeypatch.setattr(NexusModsSearchTool, "run", fail_leaf_tool)
    monkeypatch.setattr(LoversLabGoogleSearchTool, "run", fail_leaf_tool)
    monkeypatch.setattr(LoversLabSearchScrapeTool, "run", fail_leaf_tool)

    with Session(engine) as session:
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
    assert [match.title for match in matches] == ["XXTB Boundary Online Result"]


@pytest.mark.asyncio
async def test_find_matches_filters_online_results_by_distinctive_query_term(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    async def fake_run(self, query, query_plan, evidence_id=None, conservative_mode=False):  # noqa: ARG001
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
        return WebSearchOutput(
            results=[SearchResult(score=99, mod=unrelated, tool_name="nexusmods_search")],
            evidence=[],
        )

    monkeypatch.setattr("app.services.agent.search_orchestrator.WebSearchTool.run", fake_run)

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


@pytest.mark.asyncio
async def test_find_matches_logs_web_search_skipped_when_local_matches_sufficient(monkeypatch, caplog):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    caplog.set_level(logging.INFO)

    async def fake_local_run(self, tool_input):  # noqa: ARG001
        local_mod = Mod(
            source="nexusmods",
            external_id="local-sufficient",
            game="Stellar Blade",
            game_domain="stellarblade",
            title="XXTB - Local Strong Match",
            url="https://example.com/local-sufficient",
            first_seen_at="2026-05-20T00:00:00+00:00",
            last_seen_at="2026-05-20T00:00:00+00:00",
        )
        self.session.add(local_mod)
        self.session.flush()
        return [SearchResult(score=3, mod=local_mod, tool_name="local_db")]

    async def fail_web_search(self, query, query_plan, evidence_id=None, conservative_mode=False):  # noqa: ARG001
        raise AssertionError("web_search should not run when local matches are sufficient")

    monkeypatch.setattr("app.services.agent.search_orchestrator.distinctive_query_terms", lambda _q: [])
    monkeypatch.setattr("app.services.agent.search_orchestrator.LocalDbSearchTool.run", fake_local_run)
    monkeypatch.setattr("app.services.agent.search_orchestrator.WebSearchTool.run", fail_web_search)

    with Session(engine) as session:
        matches = await AgentSearchOrchestrator(session).find_matches(
            query="XXTB的mod",
            query_plan={
                "keywords": ["XXTB"],
                "games": [],
                "game_domains": [],
                "categories": [],
                "sources": [],
                "adult_content": None,
                "sort_field": "updated_at_remote",
                "sort_order": "desc",
                "limit": 8,
                "evidence_id": "ev_skip_case",
            },
            llm_available=False,
            provider="ollama",
            api_key="",
            base_url="",
            model="qwen3:8b",
        )

    assert [match.title for match in matches] == ["XXTB - Local Strong Match"]
    assert any(
        "agent.tool name=web_search status=skipped reason=local_matches_sufficient results=0 evidence_id=ev_skip_case"
        in record.message
        for record in caplog.records
    )

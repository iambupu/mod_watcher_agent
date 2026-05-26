import logging

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.services.agent import query_planner as query_planner_module
from app.services.agent.tools.query_planning_tool import QueryPlanningInput, QueryPlanningTool


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.mark.asyncio
async def test_query_planning_tool_uses_fallback_and_logs_plan(caplog):
    caplog.set_level(logging.INFO)
    engine = _engine()

    with Session(engine) as session:
        output = await QueryPlanningTool(session).run(
            QueryPlanningInput(query="有什么mod支持怀孕玩法", llm_available=False)
        )

    assert output.source == "fallback"
    assert output.query_plan["_agent_planning_source"] == "fallback"
    assert output.query_plan["_agent_llm_planning_used"] is False
    assert output.query_plan["_agent_fallback_planning_used"] is True
    assert output.query_plan["_agent_context_plan_used"] is False
    assert output.query_plan["intent"] == "search"
    assert output.query_plan.get("compatibility_terms", []) == []
    assert "pregnancy" in output.query_plan["keywords"] or "怀孕" in output.query_plan["keywords"]
    assert any("agent.tool name=query_planning status=succeeded source=fallback" in item.message for item in caplog.records)
    assert any(
        "agent.chat.plan" in item.message
        and "planning_source=fallback" in item.message
        and "llm_planning_used=False" in item.message
        and "intent=search" in item.message
        for item in caplog.records
    )


@pytest.mark.asyncio
async def test_query_planning_tool_keeps_llm_plan_over_current_turn_context_fallback():
    engine = _engine()

    async def fake_planner(**kwargs):
        assert kwargs["query"] == "有什么相关风格的mod"
        return {"intent": "search", "keywords": ["相关"], "evidence_id": "ev_plan"}

    with Session(engine) as session:
        output = await QueryPlanningTool(session, planner=fake_planner).run(
            QueryPlanningInput(
                query="有什么相关风格的mod",
                llm_available=True,
                provider="test",
                api_key="key",
                model="model",
                context_query_plan={"keywords": ["bimbo"], "sources": ["loverslab"]},
            )
        )

    assert output.source == "llm"
    assert output.evidence_id == "ev_plan"
    assert output.query_plan["_agent_planning_source"] == "llm"
    assert output.query_plan["_agent_llm_planning_used"] is True
    assert output.query_plan["_agent_fallback_planning_used"] is False
    assert output.query_plan["_agent_context_plan_used"] is True
    assert output.query_plan["keywords"] == ["相关"]
    assert output.query_plan["sources"] == []


@pytest.mark.asyncio
async def test_query_planning_tool_allows_llm_plan_to_inherit_explicit_context_scope():
    engine = _engine()

    async def fake_planner(**kwargs):
        return {"intent": "search", "keywords": ["related"], "evidence_id": "ev_plan"}

    with Session(engine) as session:
        output = await QueryPlanningTool(session, planner=fake_planner).run(
            QueryPlanningInput(
                query="继续找相关的",
                llm_available=True,
                provider="test",
                api_key="key",
                model="model",
                context_query_plan={
                    "keywords": ["bimbo"],
                    "sources": ["loverslab"],
                    "_agent_context_signal": {"inherited": True, "topic_shift": False},
                },
            )
        )

    assert output.source == "llm"
    assert output.query_plan["keywords"] == ["related"]
    assert output.query_plan["sources"] == ["loverslab"]


@pytest.mark.asyncio
async def test_query_planning_tool_uses_runtime_planner_module_binding(monkeypatch):
    engine = _engine()

    async def fake_module_planner(**kwargs):
        assert kwargs["query"] == "爱的实验室有什么体系mod"
        return {"intent": "search", "keywords": ["framework"], "sources": ["loverslab"], "evidence_id": "ev_module"}

    monkeypatch.setattr(query_planner_module, "plan_query_with_llm", fake_module_planner)

    with Session(engine) as session:
        output = await QueryPlanningTool(session).run(
            QueryPlanningInput(
                query="爱的实验室有什么体系mod",
                llm_available=True,
                provider="test",
                api_key="key",
                model="model",
            )
        )

    assert output.source == "llm"
    assert output.evidence_id == "ev_module"
    assert output.query_plan["_agent_planning_source"] == "llm"
    assert output.query_plan["sources"] == ["loverslab"]


@pytest.mark.asyncio
async def test_query_planning_tool_preserves_llm_semantic_signals():
    engine = _engine()

    async def fake_planner(**kwargs):
        return {
            "intent": "search",
            "keywords": ["体系"],
            "sources": ["loverslab"],
            "semantic_anchors": ["framework"],
            "semantic_domains": ["source_scope"],
            "evidence_id": "ev_llm_semantic",
        }

    with Session(engine) as session:
        output = await QueryPlanningTool(session, planner=fake_planner).run(
            QueryPlanningInput(
                query="爱的实验室有什么体系mod",
                llm_available=True,
                provider="test",
                api_key="key",
                model="model",
            )
        )

    assert output.source == "llm"
    assert output.query_plan["_agent_semantic_anchors"] == ["framework"]
    assert output.query_plan["_agent_semantic_domains"] == ["source_scope"]
    assert output.query_plan["_agent_semantic_source"] == "llm"


@pytest.mark.asyncio
async def test_query_planning_tool_does_not_apply_text_taxonomy_over_llm_plan_without_anchors():
    engine = _engine()

    async def fake_planner(**kwargs):
        return {
            "intent": "search",
            "keywords": ["怀孕玩法"],
            "semantic_anchors": [],
            "semantic_domains": [],
            "evidence_id": "ev_llm_no_anchors",
        }

    with Session(engine) as session:
        output = await QueryPlanningTool(session, planner=fake_planner).run(
            QueryPlanningInput(
                query="有什么mod支持怀孕玩法",
                llm_available=True,
                provider="test",
                api_key="key",
                model="model",
            )
        )

    assert output.source == "llm"
    assert output.query_plan["keywords"] == ["怀孕玩法"]
    assert "pregnancy" not in output.query_plan["keywords"]
    assert "_agent_semantic_anchors" not in output.query_plan


@pytest.mark.asyncio
async def test_query_planning_tool_expands_semantics_from_llm_anchors_only():
    engine = _engine()

    async def fake_planner(**kwargs):
        return {
            "intent": "search",
            "keywords": ["服装"],
            "semantic_anchors": ["sexworker_style", "outfit"],
            "semantic_domains": ["identity_style", "content_type"],
            "evidence_id": "ev_llm_style",
        }

    with Session(engine) as session:
        output = await QueryPlanningTool(session, planner=fake_planner).run(
            QueryPlanningInput(
                query="有什么妓女风格的服装MOD",
                llm_available=True,
                provider="test",
                api_key="key",
                model="model",
            )
        )

    assert output.source == "llm"
    assert "prostitute" in output.query_plan["keywords"]
    assert "outfit" in output.query_plan["keywords"]
    assert "roleplay" not in output.query_plan["keywords"]
    assert "gameplay" not in output.query_plan["keywords"]
    assert output.query_plan["_agent_semantic_source"] == "llm"


@pytest.mark.asyncio
async def test_query_planning_tool_degrades_to_fallback_when_llm_planner_fails(caplog):
    caplog.set_level(logging.INFO)
    engine = _engine()

    async def failing_planner(**kwargs):  # noqa: ARG001
        raise RuntimeError("planner unavailable")

    with Session(engine) as session:
        output = await QueryPlanningTool(session, planner=failing_planner).run(
            QueryPlanningInput(
                query="有什么mod支持怀孕玩法",
                llm_available=True,
                evidence_id="ev_planner_error",
                provider="test",
                api_key="key",
                model="model",
            )
        )

    assert output.source == "fallback"
    assert output.query_plan["_agent_planning_source"] == "fallback"
    assert output.query_plan["_agent_llm_planning_used"] is False
    assert output.query_plan["_agent_fallback_planning_used"] is True
    assert output.query_plan["_agent_llm_planning_error_type"] == "RuntimeError"
    assert output.query_plan["evidence_id"] == "ev_planner_error"
    assert any(
        "agent.tool name=query_planning status=degraded source=llm reason=planner_error" in item.message
        and "error_type=RuntimeError" in item.message
        and "evidence_id=ev_planner_error" in item.message
        for item in caplog.records
    )


@pytest.mark.asyncio
async def test_query_planning_tool_preserves_context_evidence_id():
    engine = _engine()

    with Session(engine) as session:
        output = await QueryPlanningTool(session).run(
            QueryPlanningInput(
                query="有什么相关风格的mod",
                llm_available=False,
                context_query_plan={"keywords": ["bimbo"], "evidence_id": "ev_context"},
            )
        )

    assert output.evidence_id == "ev_context"
    assert output.query_plan["evidence_id"] == "ev_context"


@pytest.mark.asyncio
async def test_query_planning_tool_uses_canonical_evidence_id_over_llm_raw_id():
    engine = _engine()

    async def fake_planner(**kwargs):
        return {"intent": "search", "keywords": ["bimbo"], "evidence_id": "ev_llm_raw"}

    with Session(engine) as session:
        output = await QueryPlanningTool(session, planner=fake_planner).run(
            QueryPlanningInput(
                query="Skyrim bimbo mod",
                llm_available=True,
                evidence_id="ev_graph",
            )
        )

    assert output.evidence_id == "ev_graph"
    assert output.query_plan["evidence_id"] == "ev_graph"
    assert output.query_plan["_agent_raw_planning_evidence_id"] == "ev_llm_raw"
    assert output.query_plan["_agent_planning_source"] == "llm"

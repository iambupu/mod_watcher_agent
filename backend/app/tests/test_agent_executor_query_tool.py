import logging

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.services.agent.tools.executor_query_tool import ExecutorQueryInput, ExecutorQueryTool


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.mark.asyncio
async def test_executor_query_tool_builds_executor_query_plan_and_logs(caplog):
    caplog.set_level(logging.INFO)
    engine = _engine()

    with Session(engine) as session:
        output = await ExecutorQueryTool(session).run(ExecutorQueryInput(query="有什么mod支持怀孕玩法"))

    assert output.query_plan["_agent_query_plan_role"] == "executor_query"
    assert output.query_plan["_agent_context_plan_used"] is False
    assert output.query_plan["intent"] == "search"
    assert output.query_plan["open_discovery"] is True
    assert output.query_plan["retrieval_mode"] == "fuzzy"
    assert output.query_plan.get("compatibility_terms", []) == []
    assert "pregnancy" in output.query_plan["keywords"] or "怀孕" in output.query_plan["keywords"]
    assert any(
        "agent.tool name=executor_query status=succeeded role=executor_query" in item.message
        for item in caplog.records
    )
    assert any(
        "agent.chat.plan" in item.message
        and "query_plan_role=executor_query" in item.message
        and "intent=search" in item.message
        and "open_discovery=True" in item.message
        and "retrieval_mode=fuzzy" in item.message
        for item in caplog.records
    )


@pytest.mark.asyncio
async def test_executor_query_tool_merges_context_for_executor_query_plan():
    engine = _engine()

    with Session(engine) as session:
        output = await ExecutorQueryTool(session).run(
            ExecutorQueryInput(
                query="有什么相关风格的mod",
                context_query_plan={
                    "keywords": ["bimbo"],
                    "sources": ["loverslab"],
                    "_agent_context_signal": {"inherited": True, "topic_shift": False},
                    "evidence_id": "ev_context",
                },
            )
        )

    assert output.evidence_id == "ev_context"
    assert output.query_plan["keywords"] == ["bimbo"]
    assert output.query_plan["sources"] == ["loverslab"]
    assert output.query_plan["_agent_context_plan_used"] is True
    assert output.query_plan["_agent_context_signal"]["inherited"] is True


@pytest.mark.asyncio
async def test_executor_query_tool_keeps_current_strong_keywords_over_context():
    engine = _engine()

    with Session(engine) as session:
        output = await ExecutorQueryTool(session).run(
            ExecutorQueryInput(
                query="cbbe 服装",
                context_query_plan={"keywords": ["bimbo"], "sources": ["nexusmods"]},
            )
        )

    assert output.query_plan["keywords"][0] == "cbbe"
    assert "outfit" in output.query_plan["keywords"]
    assert "bimbo" not in output.query_plan["keywords"]
    assert output.query_plan["sources"] == ["nexusmods"]


@pytest.mark.asyncio
async def test_executor_query_tool_preserves_canonical_evidence_id_over_raw_context_id():
    engine = _engine()

    with Session(engine) as session:
        output = await ExecutorQueryTool(session).run(
            ExecutorQueryInput(
                query="有什么相关风格的mod",
                evidence_id="ev_graph",
                context_query_plan={"keywords": ["bimbo"], "evidence_id": "ev_context"},
            )
        )

    assert output.evidence_id == "ev_graph"
    assert output.query_plan["evidence_id"] == "ev_graph"
    assert output.query_plan["_agent_context_evidence_id"] == "ev_context"
    assert output.query_plan["_agent_query_plan_role"] == "executor_query"

import logging

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.services.agent.tools.task_understanding_tool import (
    TaskUnderstandingInput,
    TaskUnderstandingTool,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


@pytest.mark.asyncio
async def test_task_understanding_inherits_context_for_ambiguous_followup_and_logs_evidence(caplog):
    caplog.set_level(logging.INFO)
    with _session() as session:
        output = await TaskUnderstandingTool(session).run(
            TaskUnderstandingInput(
                query="有什么相关风格的mod",
                last_query_context={
                    "source": "recent_user",
                    "keywords": ["bimbo"],
                    "semantic_anchors": ["bimbo", "roleplay"],
                    "semantic_domains": ["mechanics"],
                    "game": "Skyrim Special Edition",
                    "quality_score": 0.82,
                },
                evidence_id="ev_understanding",
            )
        )

    assert output.evidence_id == "ev_understanding"
    assert output.llm_available is False
    assert output.query_plan["evidence_id"] == "ev_understanding"
    assert "bimbo" in output.query_plan["keywords"]
    assert output.query_plan["_agent_context_plan_used"] is True
    assert output.query_diagnosis["should_clarify"] is False
    assert output.query_diagnosis["known_slots"]["game"] == "Skyrim Special Edition"
    assert output.query_diagnosis["understanding"]["slots"]["game"] == "Skyrim Special Edition"
    evidence = output.query_diagnosis["understanding"]["evidence"]
    assert all(item.get("evidence_id") == "ev_understanding" for item in evidence)
    assert any(item.get("field") == "context_semantic_anchors" for item in evidence)
    assert any(
        "agent.tool name=task_understanding status=succeeded" in record.message
        and "evidence_id=ev_understanding" in record.message
        for record in caplog.records
    )

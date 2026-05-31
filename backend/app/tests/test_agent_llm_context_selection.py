import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.services.agent.planning.llm_context_selection import select_last_query_context_with_llm
from app.services.agent.schemas import AgentHistoryItem
from app.services.agent.tools.task_understanding_tool import (
    TaskUnderstandingInput,
    TaskUnderstandingTool,
)
from app.utils.json import json_object_from_text


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


class _FakeContextClient:
    async def chat(self, prompt, model, max_tokens=1024, request_timeout=None):  # noqa: ARG002
        assert "完整对话" in prompt
        assert "Stellar Blade" in prompt
        return """
        {
          "should_inherit": true,
          "keywords": ["bimbo"],
          "semantic_anchors": ["bimbo", "roleplay"],
          "semantic_domains": ["mechanics"],
          "game": "Skyrim Special Edition",
          "sort_field": "updated_at_remote",
          "sort_order": "desc",
          "confidence": 0.91,
          "reason": "用户在追问相关风格，应继承 Skyrim bimbo 玩法上下文"
        }
        """


def test_json_object_from_text_returns_only_objects():
    assert json_object_from_text('[{"not":"object"}]') is None
    assert json_object_from_text('prefix {"ok": true} suffix') == {"ok": True}


@pytest.mark.asyncio
async def test_llm_context_selection_builds_inheritable_context(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent.planning.llm_context_selection.create_llm_client",
        lambda **kwargs: _FakeContextClient(),  # noqa: ARG005
    )

    selection = await select_last_query_context_with_llm(
        query="有什么相关风格的mod",
        history=[
            AgentHistoryItem(role="user", text="Stellar Blade 服装 mod"),
            AgentHistoryItem(role="assistant", text="ok"),
            AgentHistoryItem(role="user", text="Skyrim Special Edition bimbo roleplay mod"),
        ],
        active_constraints={},
        short_last_query_context={"source": "recent_user", "keywords": ["stellar"], "quality_score": 0.7},
        memory_context={},
        shown_mod_titles=[],
        provider="openai",
        api_key="key",
        base_url="https://example.test/v1",
        model="test-model",
        evidence_id="ev_llm_context",
    )

    assert selection.status == "succeeded"
    assert selection.context["source"] == "llm_context_selection"
    assert selection.context["llm_should_inherit"] is True
    assert selection.context["game"] == "Skyrim Special Edition"
    assert selection.context["keywords"] == ["bimbo"]
    assert selection.context["semantic_anchors"] == ["bimbo", "roleplay"]
    assert selection.context["evidence_id"] == "ev_llm_context"


@pytest.mark.asyncio
async def test_task_understanding_uses_llm_selected_context(monkeypatch):
    async def fake_select_context(**kwargs):  # noqa: ARG001
        from app.services.agent.planning.llm_context_selection import LlmContextSelection

        return LlmContextSelection(
            status="succeeded",
            reason="llm_selected",
            context={
                "source": "llm_context_selection",
                "llm_should_inherit": True,
                "keywords": ["bimbo"],
                "semantic_anchors": ["bimbo", "roleplay"],
                "semantic_domains": ["mechanics"],
                "game": "Skyrim Special Edition",
                "quality_score": 0.91,
                "llm_confidence": 0.91,
                "llm_reason": "选择更早的 Skyrim bimbo 上下文",
            },
        )

    monkeypatch.setattr(
        "app.services.agent.tools.task_understanding_tool.llm_provider_config_module.provider_has_credentials",
        lambda provider, api_key: True,  # noqa: ARG005
    )
    monkeypatch.setattr(
        "app.services.agent.tools.task_understanding_tool.llm_config_module.get_llm_config",
        lambda settings, provider_override=None, model_override=None: (  # noqa: ARG005
            "openai",
            "key",
            "https://example.test/v1",
            "test-model",
        ),
    )
    monkeypatch.setattr(
        "app.services.agent.tools.task_understanding_tool.select_last_query_context_with_llm",
        fake_select_context,
    )

    with _session() as session:
        output = await TaskUnderstandingTool(session=session).run(
            TaskUnderstandingInput(
                query="有什么相关风格的mod",
                history=[
                    AgentHistoryItem(role="user", text="Stellar Blade 服装 mod"),
                    AgentHistoryItem(role="assistant", text="ok"),
                    AgentHistoryItem(role="user", text="Skyrim Special Edition bimbo roleplay mod"),
                ],
                last_query_context={"source": "recent_user", "keywords": ["stellar"], "quality_score": 0.7},
                evidence_id="ev_task_llm_context",
            )
        )

    assert "bimbo" in output.query_plan["keywords"]
    assert output.query_plan["_agent_context_signal"]["source"] == "llm_context_selection"
    assert output.query_plan["_agent_context_signal"]["llm_selected"] is True
    assert output.query_diagnosis["known_slots"]["game"] == "Skyrim Special Edition"

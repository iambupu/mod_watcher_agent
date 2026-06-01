import logging

import pytest

from app.services.agent.answer_service import AgentAnswerService
from app.services.agent.schemas import AgentModMatch
from app.services.agent.tools.chat_answer_tool import ChatAnswerInput, ChatAnswerTool


def _match() -> AgentModMatch:
    return AgentModMatch(
        id=1,
        title="Pregnancy Gameplay Overhaul",
        source="loverslab",
        game="Skyrim Special Edition",
        author="Author",
        version=None,
        url="https://example.com/pregnancy",
        updated_at_remote=None,
        score=12,
    )


@pytest.mark.asyncio
async def test_chat_answer_tool_composes_response_cards_and_llm_metadata(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    async def fake_answer_matches(self, **kwargs):
        assert kwargs["query"] == "有什么mod支持怀孕玩法"
        return "LLM answer"

    async def fake_next_steps(self, **kwargs):
        return ["继续看安装风险"]

    monkeypatch.setattr(AgentAnswerService, "answer_matches", fake_answer_matches)
    monkeypatch.setattr(AgentAnswerService, "suggest_next_steps", fake_next_steps)

    output = await ChatAnswerTool().run(
        ChatAnswerInput(
            query="有什么mod支持怀孕玩法",
            query_plan={"intent": "search", "sort_field": "relevance", "sort_order": "desc"},
            matches=[_match()],
            retrieval_evidence=[{"fragment_id": "r_1", "evidence_id": "ev_answer"}],
            llm_available=True,
            provider="test-provider",
            api_key="key",
            model="test-model",
            evidence_id="ev_answer",
        )
    )

    response = output.response
    assert output.used_llm is True
    assert output.match_count == 1
    assert response.answer == "LLM answer"
    assert response.used_llm is True
    assert response.llm_provider == "test-provider"
    assert response.llm_model == "test-model"
    assert response.retrieval_evidence == [{"fragment_id": "r_1", "evidence_id": "ev_answer"}]
    assert response.evidence_id == "ev_answer"
    assert list((response.response_cards or {}).keys())[:3] == ["analysis", "evidence", "conclusion"]
    assert response.response_cards["next_steps"] == ["继续看安装风险"]
    assert any(
        "agent.tool name=answer_generation status=succeeded mode=llm" in record.message
        and "evidence_id=ev_answer" in record.message
        for record in caplog.records
    )
    assert any(
        "agent.tool name=response_card_builder status=succeeded" in record.message
        and "evidence_id=ev_answer" in record.message
        for record in caplog.records
    )
    assert any(
        "agent.tool name=chat_answer status=succeeded" in record.message
        and "evidence_id=ev_answer" in record.message
        for record in caplog.records
    )

from types import SimpleNamespace

import pytest

from app.services.agent.schemas import AgentChatRequest, AgentChatResponse, AgentModDetailRequest
from app.services.agent.workflows import understanding_stages


@pytest.mark.asyncio
async def test_diagnose_query_stage_maps_task_understanding_output(monkeypatch):
    seen = {}

    class FakeTaskUnderstandingTool:
        def __init__(self, session):
            seen["session"] = session

        async def run(self, tool_input):
            seen["input"] = tool_input
            return SimpleNamespace(
                evidence_id="ev_understanding_out",
                query_plan={"keywords": ["pregnancy"], "evidence_id": "ev_understanding_out"},
                query_diagnosis={"intent": "search"},
                preferences={"adult_content_allowed": True},
                memory_context={"merged": {"adult_content_allowed": True}},
                semantic_strategy={"task_type": "open_discovery"},
                llm_available=True,
                llm_provider="provider",
                llm_api_key="secret",
                llm_base_url="http://test",
                llm_model="model",
            )

    monkeypatch.setattr(understanding_stages, "TaskUnderstandingTool", FakeTaskUnderstandingTool)
    request = AgentChatRequest(
        message="有什么mod支持怀孕玩法",
        provider_override="override-provider",
        model_override="override-model",
    )

    update = await understanding_stages.diagnose_query_stage(
        "session",
        request=request,
        fastapi_request=object(),
        active_constraints={"source": "loverslab"},
        last_query_context={"keywords": ["pregnancy"]},
        shown_mod_titles=["Existing Mod"],
        evidence_id="ev_understanding_in",
    )

    assert seen["session"] == "session"
    assert seen["input"].query == "有什么mod支持怀孕玩法"
    assert seen["input"].provider_override == "override-provider"
    assert seen["input"].model_override == "override-model"
    assert seen["input"].active_constraints == {"source": "loverslab"}
    assert seen["input"].last_query_context == {"keywords": ["pregnancy"]}
    assert seen["input"].shown_mod_titles == ["Existing Mod"]
    assert seen["input"].evidence_id == "ev_understanding_in"
    assert update["evidence_id"] == "ev_understanding_out"
    assert update["query_plan"]["keywords"] == ["pregnancy"]
    assert update["query_diagnosis"]["intent"] == "search"
    assert update["llm_available"] is True
    assert update["llm_provider"] == "provider"


@pytest.mark.asyncio
async def test_generate_detail_answer_stage_maps_detail_tool_input(monkeypatch):
    seen = {}
    expected = AgentChatResponse(answer="detail", used_llm=False, matches=[], response_cards=None)

    class FakeDetailTool:
        def __init__(self, session):
            seen["session"] = session

        async def run(self, tool_input):
            seen["input"] = tool_input
            return expected

    monkeypatch.setattr(understanding_stages, "ModDetailAnswerTool", FakeDetailTool)
    detail_request = AgentModDetailRequest(
        mod_id=42,
        question="安装风险？",
        provider_override="provider",
        model_override="model",
    )

    update = await understanding_stages.generate_detail_answer_stage(
        "session",
        request_kind="mod_detail",
        detail_request=detail_request,
        fastapi_request=object(),
    )

    assert seen["session"] == "session"
    assert seen["input"].mod_id == 42
    assert seen["input"].question == "安装风险？"
    assert seen["input"].provider_override == "provider"
    assert seen["input"].model_override == "model"
    assert update["response"] is expected


@pytest.mark.asyncio
async def test_generate_detail_answer_stage_rejects_wrong_request_kind():
    with pytest.raises(ValueError, match="search workflow"):
        await understanding_stages.generate_detail_answer_stage(
            "session",
            request_kind="chat",
            detail_request=AgentModDetailRequest(mod_id=1),
            fastapi_request=object(),
        )

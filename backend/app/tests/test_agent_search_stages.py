import pytest

from app.services.agent.schemas import AgentChatResponse
from app.services.agent.workflows import search_stages


class _ToolExecutorOutput:
    staged_results = ["local"]
    online_results = ["online"]
    evidence = [{"tool": "local_db"}]


class _RankingOutput:
    matches = ["match"]
    evidence = [{"tool": "ranker"}]
    match_count = 1
    validator_status = "skipped"


class _AnswerOutput:
    response = AgentChatResponse(answer="ok", used_llm=False, matches=[], response_cards=None)
    used_llm = False
    match_count = 1


@pytest.mark.asyncio
async def test_execute_retrieval_stage_maps_tool_output(monkeypatch):
    seen = {}

    class FakeExecutor:
        def __init__(self, session):
            seen["session"] = session

        async def run(self, tool_input):
            seen["input"] = tool_input
            return _ToolExecutorOutput()

    monkeypatch.setattr(search_stages, "ToolExecutorTool", FakeExecutor)

    update = await search_stages.execute_retrieval_stage(
        "session",
        query="pregnancy mod",
        query_plan={"keywords": ["pregnancy"]},
        tool_plan={"parallel_groups": [{"name": "local", "tools": ["local_db_search"]}]},
        evidence_id="ev_stage",
    )

    assert seen["session"] == "session"
    assert seen["input"].query == "pregnancy mod"
    assert seen["input"].evidence_id == "ev_stage"
    assert update["retrieval_summary"]["planned_groups"] == ["local"]
    assert update["retrieval_summary"]["staged_count"] == 1
    assert update["retrieval_summary"]["online_count"] == 1
    assert update["retrieval_evidence"] == [{"tool": "local_db"}]


@pytest.mark.asyncio
async def test_rank_candidates_stage_maps_llm_config_and_output(monkeypatch):
    seen = {}

    class FakeRanker:
        name = "candidate_ranking"

        def __init__(self, session):
            seen["session"] = session

        async def run(self, tool_input):
            seen["input"] = tool_input
            return _RankingOutput()

    monkeypatch.setattr(search_stages, "CandidateRankingTool", FakeRanker)

    update = await search_stages.rank_candidates_stage(
        "session",
        query="bimbo gameplay",
        query_plan={"keywords": ["bimbo"]},
        staged_results=["local"],
        online_results=[],
        retrieval_evidence=[{"tool": "local_db"}],
        llm={"available": True, "provider": "test-provider", "api_key": "secret", "base_url": "http://test", "model": "m"},
        evidence_id="ev_rank",
    )

    assert seen["session"] == "session"
    assert seen["input"].llm_available is True
    assert seen["input"].provider == "test-provider"
    assert seen["input"].evidence_id == "ev_rank"
    assert update["ranking_summary"]["match_count"] == 1
    assert update["ranking_summary"]["validator_status"] == "skipped"
    assert update["matches"] == ["match"]


@pytest.mark.asyncio
async def test_generate_chat_answer_stage_maps_response(monkeypatch):
    seen = {}

    class FakeAnswer:
        async def run(self, tool_input):
            seen["input"] = tool_input
            return _AnswerOutput()

    monkeypatch.setattr(search_stages, "ChatAnswerTool", FakeAnswer)

    update = await search_stages.generate_chat_answer_stage(
        query="爱的实验室体系mod",
        query_plan={"sources": ["loverslab"]},
        matches=["match"],
        retrieval_evidence=[{"tool": "web_search"}],
        history=[],
        llm={"available": False},
        evidence_id="ev_answer",
    )

    assert seen["input"].query == "爱的实验室体系mod"
    assert seen["input"].matches == ["match"]
    assert seen["input"].evidence_id == "ev_answer"
    assert update["response"].answer == "ok"
    assert update["answer_summary"] == {"match_count": 1, "used_llm": False}

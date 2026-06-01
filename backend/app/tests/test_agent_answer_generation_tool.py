import logging

import pytest

from app.services.agent import answer_service as answer_service_module
from app.services.agent.answer_service import AgentAnswerService, parse_next_steps
from app.services.agent.schemas import AgentModMatch
from app.services.agent.tools.answer_generation_tool import (
    AnswerGenerationInput,
    AnswerGenerationTool,
)


def _match(title: str = "Stable Bimbo Preset") -> AgentModMatch:
    return AgentModMatch(
        id=1,
        title=title,
        source="nexusmods",
        game="Skyrim Special Edition",
        author="Author",
        version=None,
        url="https://example.com/mod",
        updated_at_remote=None,
        adult_content=False,
        score=12,
        original_summary="A stable conservative bimbo transformation preset.",
    )


@pytest.mark.asyncio
async def test_answer_generation_tool_returns_no_match_fallback_and_logs(caplog):
    caplog.set_level(logging.INFO)

    output = await AnswerGenerationTool().run(
        AnswerGenerationInput(query="unknown mod", matches=[], llm_available=True, evidence_id="ev_answer")
    )

    assert output.used_llm is False
    assert output.reason == "no_matches"
    assert "没有找到明确匹配" in output.answer
    assert any(
        "agent.tool name=answer_generation status=succeeded mode=fallback reason=no_matches" in item.message
        for item in caplog.records
    )


@pytest.mark.asyncio
async def test_answer_generation_tool_uses_intent_fallback_when_llm_unavailable():
    output = await AnswerGenerationTool().run(
        AnswerGenerationInput(
            query="这两个哪个更适合新手",
            query_plan={"intent": "comparison"},
            matches=[_match()],
            llm_available=False,
        )
    )

    assert output.used_llm is False
    assert output.reason == "llm_unavailable"
    assert "更推荐：Stable Bimbo Preset" in output.answer


@pytest.mark.asyncio
async def test_answer_generation_tool_runs_llm_and_next_steps(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    async def fake_answer_matches(self, **kwargs):
        assert kwargs["query"] == "bimbo roleplay"
        assert kwargs["matches"][0].title == "Stable Bimbo Preset"
        return "LLM 推荐 Stable Bimbo Preset。"

    async def fake_next_steps(self, **kwargs):
        assert kwargs["answer"] == "LLM 推荐 Stable Bimbo Preset。"
        return ["继续看安装风险"]

    monkeypatch.setattr(AgentAnswerService, "answer_matches", fake_answer_matches)
    monkeypatch.setattr(AgentAnswerService, "suggest_next_steps", fake_next_steps)

    output = await AnswerGenerationTool().run(
        AnswerGenerationInput(
            query="bimbo roleplay",
            matches=[_match()],
            llm_available=True,
            provider="test",
            api_key="key",
            model="model",
            evidence_id="ev_answer",
        )
    )

    assert output.used_llm is True
    assert output.answer == "LLM 推荐 Stable Bimbo Preset。"
    assert output.next_steps == ["继续看安装风险"]
    assert any(
        "agent.tool name=answer_generation status=succeeded mode=llm matches=1 next_steps=1" in item.message
        for item in caplog.records
    )


@pytest.mark.asyncio
async def test_answer_generation_tool_falls_back_when_llm_answer_is_empty(monkeypatch):
    async def fake_answer_matches(self, **kwargs):
        return ""

    monkeypatch.setattr(AgentAnswerService, "answer_matches", fake_answer_matches)

    output = await AnswerGenerationTool().run(
        AnswerGenerationInput(query="bimbo roleplay", matches=[_match()], llm_available=True)
    )

    assert output.used_llm is False
    assert output.reason == "llm_empty_or_error"
    assert output.answer.startswith("找到以下相关 Mod")


@pytest.mark.asyncio
async def test_answer_generation_tool_falls_back_when_llm_answer_is_fetch_error(monkeypatch):
    async def fake_answer_matches(self, **kwargs):
        return "failed to fetch"

    monkeypatch.setattr(AgentAnswerService, "answer_matches", fake_answer_matches)

    output = await AnswerGenerationTool().run(
        AnswerGenerationInput(query="bimbo roleplay", matches=[_match()], llm_available=True)
    )

    assert output.used_llm is False
    assert output.reason == "llm_empty_or_error"


@pytest.mark.asyncio
async def test_answer_matches_prompt_includes_summaries_and_open_discovery_guidance(monkeypatch):
    captured = {}

    class FakeClient:
        async def chat(self, prompt, model, max_tokens=1024):  # noqa: ARG002
            captured["prompt"] = prompt
            captured["max_tokens"] = max_tokens
            return "推荐 Bimbos of Skyrim。"

    monkeypatch.setattr(answer_service_module, "create_llm_client", lambda **kwargs: FakeClient())  # noqa: ARG005

    await AgentAnswerService().answer_matches(
        query="天际有什么扮演bimbo的MOD",
        matches=[
            AgentModMatch(
                id=1,
                title="Bimbos Of Skyrim LE/SE 1.9.0.7",
                source="loverslab",
                game="skyrimspecialedition",
                author="Author",
                version="1.9.0.7",
                url="https://example.com/bos",
                updated_at_remote=None,
                adult_content=True,
                score=100,
                rank_reason="命中工具：local_db_search；基础相关性 100。",
                original_summary="Adds bimbofied NPCs, quests, and a bimbofication curse for player and followers.",
                translated_summary="加入 bimbo 化 NPC、任务，以及可影响玩家或随从的 bimbofication curse。",
            )
        ],
        provider="test",
        api_key="key",
        base_url="",
        model="model",
        history=[],
    )

    prompt = captured["prompt"]
    assert "original_summary=Adds bimbofied NPCs" in prompt
    assert "translated_summary=加入 bimbo 化 NPC" in prompt
    assert "rank_reason=命中工具：local_db_search" in prompt
    assert "核心玩法、外观/身体配套、对话或生态扩展、安装与兼容风险" in prompt
    assert "不要把 preset/addon/overhaul/tats 类配套放在核心前面" in prompt
    assert captured["max_tokens"] == 900


def test_parse_next_steps_drops_truncated_json_array_line():
    assert parse_next_steps('["这个 MOD 有哪些安装风险？') == []

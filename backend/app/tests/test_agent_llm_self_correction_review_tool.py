from dataclasses import replace

import pytest

from app.services.agent.self_correction.self_correction_evidence import (
    build_self_correction_evidence,
)
from app.services.agent.tools.llm_self_correction_review_tool import (
    LLMSelfCorrectionReviewInput,
    LLMSelfCorrectionReviewTool,
)


class _FakeClient:
    def __init__(self, outputs: list[str]):
        self.outputs = outputs
        self.prompts: list[str] = []

    async def chat(self, prompt: str, model: str, max_tokens: int = 1024, request_timeout: float | None = None) -> str:
        self.prompts.append(prompt)
        return self.outputs.pop(0)


def _input() -> LLMSelfCorrectionReviewInput:
    evidence = build_self_correction_evidence(
        original_query="只看任务线 Mod",
        query_plan={
            "_agent_semantic_strategy": {
                "user_goal": "只看任务线 Mod",
                "direct_match_definition": ["必须是 questline"],
            },
            "_agent_candidate_semantic_judge": {"fit_counts": {"direct_match": 0}, "gaps": ["缺少任务线"]},
        },
        matches=[],
    )
    return LLMSelfCorrectionReviewInput(
        evidence=evidence,
        round_index=1,
        max_rounds=2,
        phase="round_review",
        llm_available=True,
        provider="ollama",
        base_url="http://localhost:11434",
        model="qwen",
    )


@pytest.mark.asyncio
async def test_llm_self_correction_review_requires_llm_available():
    result = await LLMSelfCorrectionReviewTool().run(replace(_input(), llm_available=False))

    assert result.llm_review_status == "unavailable"
    assert result.used_llm is False
    assert result.action == "fallback_no_direct_match"


@pytest.mark.asyncio
async def test_llm_self_correction_review_accepts_valid_json():
    client = _FakeClient(
        [
            '{"action":"refine_retrieval","detected_errors":["direct不足"],'
            '"reason_summary":"需要二轮检索","correction_plan":{"keywords":["questline"]},'
            '"changed_fields":["keywords"],"preserved_constraints":["game"],'
            '"rejected_changes":[],"confidence":0.8}'
        ]
    )
    tool = LLMSelfCorrectionReviewTool(client_factory=lambda provider, api_key, base_url: client)

    result = await tool.run(_input())

    assert result.llm_review_status == "passed"
    assert result.used_llm is True
    assert result.action == "refine_retrieval"
    assert result.changed_fields == ["keywords"]
    assert "必须只输出一个 JSON object" in client.prompts[0]


@pytest.mark.asyncio
async def test_llm_self_correction_review_repairs_invalid_json_once():
    client = _FakeClient(
        [
            "not json",
            '{"action":"continue_answer","detected_errors":[],"reason_summary":"可直接回答",'
            '"correction_plan":{},"changed_fields":[],"preserved_constraints":["game"],'
            '"rejected_changes":[],"confidence":0.9}',
        ]
    )
    tool = LLMSelfCorrectionReviewTool(client_factory=lambda provider, api_key, base_url: client)

    result = await tool.run(_input())

    assert result.llm_review_status == "repaired"
    assert result.action == "continue_answer"
    assert len(client.prompts) == 2


@pytest.mark.asyncio
async def test_llm_self_correction_review_invalid_after_repair_degrades_explicitly():
    client = _FakeClient(["not json", "still not json"])
    tool = LLMSelfCorrectionReviewTool(client_factory=lambda provider, api_key, base_url: client)

    result = await tool.run(_input())

    assert result.llm_review_status == "invalid"
    assert result.action == "fallback_no_direct_match"
    assert result.detected_errors == ["llm_review_invalid_output"]

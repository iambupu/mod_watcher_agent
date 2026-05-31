import pytest

from app.services.agent.judging.candidate_semantic_judge import (
    CandidateSemanticJudgeInput,
    CandidateSemanticJudgeTool,
)
from app.services.agent.schemas import AgentModMatch


def _match(mod_id: int, title: str) -> AgentModMatch:
    return AgentModMatch(
        id=mod_id,
        title=title,
        source="loverslab",
        game="Skyrim Special Edition",
        author=None,
        version=None,
        url=f"https://example.com/{mod_id}",
        updated_at_remote=None,
        score=10,
        original_summary="Bimbo roleplay mechanics and related content.",
    )


@pytest.mark.asyncio
async def test_candidate_semantic_judge_accepts_llm_grouping():
    async def fake_judge(tool_input):
        assert tool_input.semantic_strategy["task_type"] == "open_discovery"
        return {
            "judgements": [
                {
                    "candidate_id": 1,
                    "relevance": "high",
                    "group": "core_gameplay",
                    "reason": "directly supports bimbo roleplay",
                },
                {
                    "candidate_id": 2,
                    "relevance": "medium",
                    "group": "visual_support",
                    "reason": "visual add-on",
                },
            ],
            "groups": [
                {
                    "name": "core_gameplay",
                    "label": "核心玩法",
                    "candidate_ids": [1],
                    "reason": "main mechanics",
                }
            ],
            "gaps": ["缺少安装风险证据"],
            "rejected": [],
        }

    output = await CandidateSemanticJudgeTool(judge=fake_judge).run(
        CandidateSemanticJudgeInput(
            query="天际有什么扮演 bimbo 的 MOD",
            semantic_strategy={"task_type": "open_discovery"},
            candidates=[_match(1, "Bimbo Roleplay Framework"), _match(2, "Bimbo Outfit")],
            llm_available=True,
        )
    )

    assert output.status == "succeeded"
    assert output.used_llm is True
    assert [item.relevance for item in output.judgements] == ["high", "medium"]
    assert output.groups[0].label == "核心玩法"
    assert output.gaps == ["缺少安装风险证据"]


@pytest.mark.asyncio
async def test_candidate_semantic_judge_filters_dirty_group_ids_and_rejects_bool_candidate_id():
    async def fake_judge(tool_input):
        return {
            "judgements": [
                {
                    "candidate_id": "2",
                    "relevance": "medium",
                    "group": "visual_support",
                    "reason": "numeric string is normalized",
                },
            ],
            "groups": [
                {
                    "name": "visual_support",
                    "label": "视觉支持",
                    "candidate_ids": [True, "2", 0, -1, "bad", 2],
                    "reason": "dirty ids",
                }
            ],
            "gaps": [],
            "rejected": [{"candidate_id": False, "reason": "bad bool id"}],
        }

    output = await CandidateSemanticJudgeTool(judge=fake_judge).run(
        CandidateSemanticJudgeInput(
            query="天际有什么扮演 bimbo 的 MOD",
            candidates=[_match(1, "Bimbo Roleplay Framework"), _match(2, "Bimbo Outfit")],
            llm_available=True,
        )
    )

    assert output.status == "degraded"
    assert output.fallback_reason == "ValidationError"


@pytest.mark.asyncio
async def test_candidate_semantic_judge_filters_dirty_group_ids():
    async def fake_judge(tool_input):
        return {
            "judgements": [
                {
                    "candidate_id": "2",
                    "relevance": "medium",
                    "group": "visual_support",
                    "reason": "numeric string is normalized",
                },
            ],
            "groups": [
                {
                    "name": "visual_support",
                    "label": "视觉支持",
                    "candidate_ids": [True, "2", 0, -1, "bad", 2],
                    "reason": "dirty ids",
                }
            ],
            "gaps": [],
            "rejected": [],
        }

    output = await CandidateSemanticJudgeTool(judge=fake_judge).run(
        CandidateSemanticJudgeInput(
            query="天际有什么扮演 bimbo 的 MOD",
            candidates=[_match(1, "Bimbo Roleplay Framework"), _match(2, "Bimbo Outfit")],
            llm_available=True,
        )
    )

    assert output.status == "succeeded"
    assert output.judgements[0].candidate_id == 2
    assert output.groups[0].candidate_ids == [2]


@pytest.mark.asyncio
async def test_candidate_semantic_judge_invalid_json_degrades_to_fallback():
    async def broken_judge(tool_input):
        return {"judgements": [{"candidate_id": 1, "relevance": "excellent", "group": "core_gameplay"}]}

    output = await CandidateSemanticJudgeTool(judge=broken_judge).run(
        CandidateSemanticJudgeInput(
            query="天际有什么扮演 bimbo 的 MOD",
            candidates=[_match(1, "Bimbo Roleplay Framework")],
            llm_available=True,
            evidence_id="ev_judge",
        )
    )

    assert output.status == "degraded"
    assert output.used_llm is False
    assert output.fallback_reason == "ValidationError"
    assert output.judgements[0].relevance == "medium"


@pytest.mark.asyncio
async def test_candidate_semantic_judge_skips_when_llm_unavailable():
    output = await CandidateSemanticJudgeTool().run(
        CandidateSemanticJudgeInput(
            query="天际有什么扮演 bimbo 的 MOD",
            candidates=[_match(1, "Bimbo Roleplay Framework")],
            llm_available=False,
        )
    )

    assert output.status == "skipped"
    assert output.fallback_reason == "llm_unavailable"
    assert output.used_llm is False

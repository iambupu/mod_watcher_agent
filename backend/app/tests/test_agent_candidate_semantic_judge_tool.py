import pytest

from app.services.agent.judging import candidate_semantic_judge as judge_module
from app.services.agent.judging.candidate_semantic_judge import (
    CANDIDATE_SEMANTIC_JUDGE_TIMEOUT_SECONDS,
    CandidateSemanticJudgeInput,
    CandidateSemanticJudgeTool,
)
from app.services.agent.judging.candidate_semantic_judge_prompt import (
    build_candidate_semantic_judge_prompt,
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


def test_candidate_semantic_judge_prompt_requires_category_semantic_compatibility():
    prompt = build_candidate_semantic_judge_prompt(
        query="只看天际的R18女性服装",
        semantic_strategy={
            "user_goal": "只看天际的R18女性服装",
            "direct_match_definition": ["Skyrim adult female clothing or outfit style wearable items"],
        },
        candidates=[
            AgentModMatch(
                id=10,
                title="Obi's Battle Bikini 4K 3BA BHUNP UBE",
                source="nexusmods",
                game="Skyrim Special Edition",
                category="Armour",
                author=None,
                version=None,
                url="https://example.com/10",
                updated_at_remote=None,
                adult_content=True,
                score=10,
                original_summary="Requested skimpy piece. Made from scratch.",
            )
        ],
        retrieval_evidence=[],
    )

    assert "category_semantic_compatibility" in prompt
    assert "category 是来源站点的粗标签，不等于用户语义目标" in prompt
    assert "category=Armour/Armor" in prompt
    assert "bikini、lingerie、dress、outfit、robe、clothing" in prompt
    assert "仍需检查游戏、内容分级、性别/身体体系、用户排除条件等硬约束" in prompt
    assert "不要要求候选标题或摘要逐字包含用户问题原句" in prompt
    assert "adult_content=true 判断，不要求 title/summary 写“R18”" in prompt
    assert "不要只因为没有“女性服装”四个字就降为 support_context" in prompt


@pytest.mark.asyncio
async def test_candidate_semantic_judge_accepts_llm_grouping():
    async def fake_judge(tool_input):
        assert tool_input.semantic_strategy["task_type"] == "open_discovery"
        return {
            "judgements": [
                {
                    "candidate_id": 1,
                    "relevance": "high",
                    "fit_type": "direct_match",
                    "group": "core_gameplay",
                    "reason": "directly supports bimbo roleplay",
                    "evidence": ["mechanics"],
                    "violations": [],
                },
                {
                    "candidate_id": 2,
                    "relevance": "medium",
                    "fit_type": "support_context",
                    "group": "visual_support",
                    "reason": "visual add-on",
                    "evidence": ["outfit"],
                    "violations": ["not_core_gameplay"],
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
    assert [item.fit_type for item in output.judgements] == ["direct_match", "support_context"]
    assert output.judgements[1].violations == ["not_core_gameplay"]
    assert output.groups[0].label == "核心玩法"
    assert output.gaps == ["缺少安装风险证据"]


@pytest.mark.asyncio
async def test_candidate_semantic_judge_accepts_category_semantic_compatibility():
    async def fake_judge(tool_input):
        return {
            "judgements": [
                {
                    "candidate_id": 1,
                    "relevance": "high",
                    "fit_type": "direct_match",
                    "group": "visual_support",
                    "category_semantic_compatibility": "compatible",
                    "category_compatibility_reason": "Armour is a source label; bikini title and adult flag match clothing intent.",
                    "reason": "adult bikini wearable for Skyrim",
                    "evidence": ["title contains bikini", "category=Armour", "adult_content=true"],
                    "violations": [],
                }
            ],
            "groups": [],
            "gaps": [],
            "rejected": [],
        }

    candidate = _match(1, "A sexy straps bikini for UNP")
    candidate = candidate.model_copy(
        update={
            "source": "nexusmods",
            "category": "Armour",
            "adult_content": True,
            "original_summary": "Skimpy bikini wearable for UNP.",
        }
    )

    output = await CandidateSemanticJudgeTool(judge=fake_judge).run(
        CandidateSemanticJudgeInput(
            query="只看天际的R18女性服装",
            semantic_strategy={"task_type": "open_discovery"},
            candidates=[candidate],
            llm_available=True,
        )
    )

    assert output.status == "succeeded"
    assert output.judgements[0].fit_type == "direct_match"
    assert output.judgements[0].category_semantic_compatibility == "compatible"
    assert "bikini title" in output.judgements[0].category_compatibility_reason


@pytest.mark.asyncio
async def test_candidate_semantic_judge_uses_extended_llm_timeout(monkeypatch):
    seen = {}

    class FakeClient:
        async def chat(self, prompt, *, model, max_tokens, request_timeout):
            seen["request_timeout"] = request_timeout
            return """
            {
              "judgements": [
                {
                  "candidate_id": 1,
                  "relevance": "high",
                  "fit_type": "direct_match",
                  "group": "visual_support",
                  "category_semantic_compatibility": "compatible",
                  "category_compatibility_reason": "category matches clothing intent",
                  "reason": "direct clothing match"
                }
              ],
              "groups": [],
              "gaps": [],
              "rejected": []
            }
            """

    def fake_create_llm_client(provider, api_key, base_url):
        return FakeClient()

    monkeypatch.setattr(judge_module, "create_llm_client", fake_create_llm_client)

    output = await CandidateSemanticJudgeTool().run(
        CandidateSemanticJudgeInput(
            query="只看天际的R18女性服装",
            semantic_strategy={"direct_match_definition": ["female clothing"]},
            candidates=[_match(1, "A sexy straps bikini for UNP")],
            llm_available=True,
            provider="ollama",
            model="qwen3:8b",
        )
    )

    assert output.status == "succeeded"
    assert seen["request_timeout"] == CANDIDATE_SEMANTIC_JUDGE_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_candidate_semantic_judge_drops_stale_no_direct_gaps_when_direct_matches_exist():
    async def fake_judge(tool_input):
        return {
            "judgements": [
                {
                    "candidate_id": 1,
                    "relevance": "high",
                    "fit_type": "direct_match",
                    "group": "visual_support",
                    "reason": "direct match exists",
                }
            ],
            "groups": [],
            "gaps": [
                "未找到明确的直接匹配项",
                "缺少标题或描述中明确包含用户原句",
                "缺少明确标注 R18 的直接匹配项",
                "缺少明确提及'天际'的标题或描述",
                "缺少安装风险证据",
            ],
            "rejected": [],
        }

    output = await CandidateSemanticJudgeTool(judge=fake_judge).run(
        CandidateSemanticJudgeInput(
            query="只看天际的R18女性服装",
            candidates=[_match(1, "A sexy straps bikini for UNP")],
            llm_available=True,
        )
    )

    assert output.status == "succeeded"
    assert output.gaps == ["缺少安装风险证据"]


@pytest.mark.asyncio
async def test_candidate_semantic_judge_filters_dirty_group_ids_and_rejects_bool_candidate_id():
    async def fake_judge(tool_input):
        return {
            "judgements": [
                {
                    "candidate_id": "2",
                    "relevance": "medium",
                    "fit_type": "support_context",
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
                    "fit_type": "support_context",
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
    assert output.judgements[0].relevance == "low"
    assert output.judgements[0].fit_type == "uncertain"


@pytest.mark.asyncio
async def test_candidate_semantic_judge_invalid_fit_type_degrades_to_fallback():
    async def broken_judge(tool_input):
        return {
            "judgements": [
                {
                    "candidate_id": 1,
                    "relevance": "high",
                    "fit_type": "primary",
                    "group": "core_gameplay",
                }
            ]
        }

    output = await CandidateSemanticJudgeTool(judge=broken_judge).run(
        CandidateSemanticJudgeInput(
            query="只看某类主结果",
            candidates=[_match(1, "Direct Item")],
            llm_available=True,
        )
    )

    assert output.status == "degraded"
    assert output.judgements[0].fit_type == "uncertain"


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

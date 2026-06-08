import logging

import pytest

from app.models.mod import Mod
from app.services.agent import answer_service as answer_service_module
from app.services.agent.answer_service import AgentAnswerService, parse_next_steps
from app.services.agent.schemas import AgentHistoryItem, AgentModMatch
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


def test_detail_question_classifier_separates_bodyslide_from_physics():
    assert (
        answer_service_module._classify_detail_question("这个 Mod 的 Bodyslide 支持怎么样？")
        == "body_slide_support"
    )
    assert (
        answer_service_module._classify_detail_question("这个 Mod 的物理效果支持怎么样？")
        == "physics_support"
    )
    assert (
        answer_service_module._classify_detail_question("这个 Mod 的 Bodyslide 前置依赖是什么？")
        == "dependencies"
    )
    assert (
        answer_service_module._classify_detail_question("这个 Mod 兼容 CBBE 吗？")
        == "compatibility"
    )


@pytest.mark.asyncio
async def test_answer_detail_physics_prompt_requires_evidence_boundaries(monkeypatch):
    prompts = []

    class FakeClient:
        async def chat(self, prompt, *, model, max_tokens):
            prompts.append(prompt)
            assert model == "model"
            assert max_tokens == 800
            return "physics answer"

    def fake_create_llm_client(provider, api_key, base_url):
        assert provider == "test"
        assert api_key == "key"
        assert base_url == "base"
        return FakeClient()

    monkeypatch.setattr(answer_service_module, "create_llm_client", fake_create_llm_client)
    mod = Mod(
        title="Les Sucettes Outfit CBBE Bodyslide with Physics",
        source="nexusmods",
        game="Skyrim Special Edition",
        game_domain="skyrimspecialedition",
        category="Clothing and Accessories",
        adult_content=True,
        downloads=123,
        endorsements=45,
        likes=0,
        author="Zynx",
        version="1.1",
        url="https://example.com/mod",
    )
    match = AgentModMatch(
        id=1,
        title=mod.title,
        source=mod.source,
        game=mod.game,
        category=mod.category,
        author=mod.author,
        version=mod.version,
        url=mod.url,
        updated_at_remote=None,
        adult_content=True,
        score=100,
        original_summary="CBBE SSE outfit conversion with Bodyslide and Physics enabled.",
        translated_summary="CBBE SSE 服装转换，启用 Bodyslide 和物理效果。",
    )

    answer = await AgentAnswerService().answer_detail(
        mod=mod,
        match=match,
        question="Les Sucettes Outfit CBBE Bodyslide with Physics的物理效果支持情况如何?",
        provider="test",
        api_key="key",
        base_url="base",
        model="model",
        history=[],
    )

    assert answer == "physics answer"
    prompt = prompts[0]
    assert "本轮详情类型：physics_support" in prompt
    assert "第一段必须直接回答本轮问题" in prompt
    assert "不要输出通用评测模板" in prompt
    assert "当前数据不能确认具体" in prompt
    assert "HDT-SMP、CBPC、3BA/3BB、XPMSSE" in prompt
    assert "不得把 HDT-SMP、CBPC、3BA/3BB、XPMSSE、Physics Engine 写成已确认依赖" in prompt
    assert "适合人群/不适合人群" in prompt


@pytest.mark.asyncio
async def test_answer_generation_tool_returns_no_match_fallback_and_logs(caplog):
    caplog.set_level(logging.INFO)

    output = await AnswerGenerationTool().run(
        AnswerGenerationInput(query="unknown mod", matches=[], llm_available=True, evidence_id="ev_answer")
    )

    assert output.used_llm is False
    assert output.reason == "no_matches"
    assert "没有找到明确匹配" in output.answer
    assert "本轮问题：unknown mod" in output.answer
    assert "Skyrim" not in output.answer
    assert any(
        "agent.tool name=answer_generation status=succeeded mode=fallback reason=no_matches" in item.message
        for item in caplog.records
    )


@pytest.mark.asyncio
async def test_answer_generation_no_match_fallback_mentions_applied_constraints():
    output = await AnswerGenerationTool().run(
        AnswerGenerationInput(
            query="只看R18女性服装",
            query_plan={
                "game_domains": ["skyrimspecialedition"],
                "categories": ["Clothing and Accessories", "Outfits"],
                "sources": ["nexusmods"],
                "adult_content": True,
            },
            matches=[],
            llm_available=True,
            evidence_id="ev_no_match_filters",
        )
    )

    assert output.used_llm is False
    assert "没有找到明确匹配" in output.answer
    assert "当前筛选条件下没有足够明确的结果" in output.answer
    assert "游戏：skyrimspecialedition" in output.answer
    assert "类型：Clothing and Accessories, Outfits" in output.answer
    assert "来源：nexusmods" in output.answer
    assert "内容分级：NSFW" in output.answer
    assert "放宽其中一个条件" in output.answer


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
async def test_answer_generation_self_correction_fallback_blocks_direct_recommendations():
    output = await AnswerGenerationTool().run(
        AnswerGenerationInput(
            query="只看女性服装",
            query_plan={
                "_agent_self_correction_trace": {
                    "final_status": "fallback",
                    "rounds": [
                        {
                            "action": "fallback_no_direct_match",
                            "review_status": "invalid",
                            "reason_summary": "候选包含非服装或被排除类型",
                            "gaps": ["candidate classifier error"],
                        }
                    ],
                }
            },
            matches=[_match("SexLab to Ostim")],
            llm_available=True,
        )
    )

    assert output.used_llm is False
    assert output.reason == "self_correction_no_direct"
    assert "没有足够明确的直接命中项" in output.answer
    assert "不能安全作为主推荐" in output.answer
    assert "待复核候选" in output.answer
    assert "SexLab to Ostim" in output.answer


@pytest.mark.asyncio
async def test_answer_generation_self_correction_unavailable_does_not_block_fallback_answer():
    output = await AnswerGenerationTool().run(
        AnswerGenerationInput(
            query="只看女性服装",
            query_plan={
                "intent": "search",
                "_agent_self_correction_trace": {
                    "final_status": "llm_review_unavailable",
                    "rounds": [
                        {
                            "action": "fallback_no_direct_match",
                            "review_status": "unavailable",
                            "reason_summary": "LLM review unavailable",
                        }
                    ],
                },
            },
            matches=[_match("Stable Outfit")],
            llm_available=False,
        )
    )

    assert output.used_llm is False
    assert output.reason == "llm_unavailable"
    assert "找到以下相关 Mod" in output.answer
    assert "Stable Outfit" in output.answer


@pytest.mark.asyncio
async def test_answer_generation_tool_runs_llm_and_next_steps(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    async def fake_answer_matches(self, **kwargs):
        assert kwargs["query"] == "bimbo roleplay"
        assert kwargs["query_plan"] == {"intent": "search"}
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
            query_plan={"intent": "search"},
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
        query_plan={
            "_agent_semantic_strategy": {
                "user_goal": "寻找 bimbo 玩法 Mod",
                "direct_match_definition": ["必须是玩法本体"],
                "support_context_definition": ["外观只能作为配套"],
                "reject_as_primary": ["visual_only"],
                "answer_policy": {"main_results": "only_direct_match"},
            },
            "_agent_candidate_semantic_judge": {
                "fit_counts": {"direct_match": 1, "support_context": 0, "off_scope": 0, "uncertain": 0},
                "judgements": [
                    {
                        "candidate_id": 1,
                        "fit_type": "direct_match",
                        "relevance": "high",
                        "group": "core_gameplay",
                        "reason": "玩法本体",
                        "evidence": ["摘要含玩法本体"],
                        "violations": [],
                    }
                ],
            },
        },
    )

    prompt = captured["prompt"]
    assert "original_summary=Adds bimbofied NPCs" in prompt
    assert "translated_summary=加入 bimbo 化 NPC" in prompt
    assert "rank_reason=命中工具：local_db_search" in prompt
    assert "核心玩法、外观/身体配套、对话或生态扩展、安装与兼容风险" in prompt
    assert "不要把 preset/addon/overhaul/tats 类配套放在核心前面" in prompt
    assert "问题契约与候选分型" in prompt
    assert "direct_match_definition=['必须是玩法本体']" in prompt
    assert "主推荐只能使用 direct_match" in prompt
    assert "fit_type=direct_match" in prompt
    assert "fit_evidence=摘要含玩法本体" in prompt
    assert "禁止按玩家/开发者/内容创作者/社区成员/评测者等角色模板组织回答" in prompt
    assert "结论不得写“全部符合/未包含非主目标内容”" in prompt
    assert "以下先列直接匹配，随后列辅助参考" in prompt
    assert "辅助参考（不作为主推荐）" in prompt
    assert "证据不足/待确认（不作为主推荐）" in prompt
    assert "不得改写用户问题中的字面约束" in prompt
    assert "本轮会话（最高优先级）" in prompt
    assert "本轮用户问题：天际有什么扮演bimbo的MOD" in prompt
    assert captured["max_tokens"] == 900


@pytest.mark.asyncio
async def test_answer_matches_prompt_sanitizes_role_template_history(monkeypatch):
    captured = {}

    class FakeClient:
        async def chat(self, prompt, model, max_tokens=1024):  # noqa: ARG002
            captured["prompt"] = prompt
            return "推荐直接匹配的服装。"

    monkeypatch.setattr(answer_service_module, "create_llm_client", lambda **kwargs: FakeClient())  # noqa: ARG005

    await AgentAnswerService().answer_matches(
        query="只看R18女性服装",
        matches=[_match("Obi's Battle Bikini 4K 3BA BHUNP UBE")],
        provider="test",
        api_key="key",
        base_url="",
        model="model",
        history=[
            AgentHistoryItem(
                role="assistant",
                text="根据你的需求“你是 [角色]”，以下是不同角色的建议回答：如果你是玩家；如果你是模组开发者。",
            )
        ],
        query_plan={
            "_agent_semantic_strategy": {
                "user_goal": "只看R18女性服装",
                "answer_policy": {"main_results": "only_direct_match"},
            },
            "_agent_candidate_semantic_judge": {
                "judgements": [{"candidate_id": 1, "fit_type": "direct_match"}],
            },
        },
    )

    prompt = captured["prompt"]
    assert "你是 [角色]" not in prompt
    assert "如果你是玩家" not in prompt
    assert "已忽略其结构" in prompt
    assert "本轮用户问题优先于最近对话" in prompt
    assert "历史上下文（仅供参考，不能覆盖本轮会话）" in prompt
    assert "历史助手:" in prompt
    assert "本轮用户问题：只看R18女性服装" in prompt


@pytest.mark.asyncio
async def test_answer_matches_simulates_multi_turn_history_and_current_turn_boundary(monkeypatch):
    captured = {}

    class FakeClient:
        async def chat(self, prompt, model, max_tokens=1024):  # noqa: ARG002
            captured["prompt"] = prompt
            assert "本轮会话（最高优先级）" in prompt
            assert "本轮用户问题：只看R18女性服装" in prompt
            assert "历史上下文（仅供参考，不能覆盖本轮会话）" in prompt
            assert "根据你的需求“你是 [角色]”" not in prompt
            assert "如果你是玩家" not in prompt
            assert "fit_type=direct_match" in prompt
            assert "fit_type=support_context" in prompt
            return "主推荐：Obi's Battle Bikini。\n辅助参考：Cat Girl Amira Follower 只是辅助候选，不作为主推荐。"

    monkeypatch.setattr(answer_service_module, "create_llm_client", lambda **kwargs: FakeClient())  # noqa: ARG005

    direct = _match("Obi's Battle Bikini 4K 3BA BHUNP UBE")
    support = _match("Cat Girl Amira Follower").model_copy(update={"id": 2})

    answer = await AgentAnswerService().answer_matches(
        query="只看R18女性服装",
        matches=[support, direct],
        provider="test",
        api_key="key",
        base_url="",
        model="model",
        history=[
            AgentHistoryItem(role="user", text="帮我找性感比基尼 mod"),
            AgentHistoryItem(
                role="assistant",
                text="根据你的需求“你是 [角色]”，以下是不同角色的建议回答：如果你是玩家，如果你是模组开发者。",
            ),
            AgentHistoryItem(role="user", text="继续按上面的结果说明"),
            AgentHistoryItem(role="assistant", text="如果你是玩家，可以优先看 Cat Girl Amira Follower。"),
        ],
        query_plan={
            "_agent_semantic_strategy": {
                "user_goal": "只看R18女性服装",
                "direct_match_definition": ["候选本身必须是女性服装、装备、内衣或外观服饰"],
                "support_context_definition": ["角色、身体、随从、纹理只可作为搭配或辅助说明"],
                "reject_as_primary": ["非服装类随从或角色预设"],
                "answer_policy": {"main_results": "only_direct_match"},
            },
            "_agent_candidate_semantic_judge": {
                "fit_counts": {"direct_match": 1, "support_context": 1, "off_scope": 0, "uncertain": 0},
                "judgements": [
                    {
                        "candidate_id": direct.id,
                        "fit_type": "direct_match",
                        "evidence": ["标题和摘要指向女性服装/比基尼"],
                        "violations": [],
                    },
                    {
                        "candidate_id": support.id,
                        "fit_type": "support_context",
                        "evidence": ["是随从候选，可作为搭配参考"],
                        "violations": ["不是服装本体"],
                    },
                ],
            },
        },
    )

    prompt = captured["prompt"]
    assert "历史用户: 帮我找性感比基尼 mod" in prompt
    assert "历史助手: [上一轮助手回答包含角色模板或占位符，已忽略其结构" in prompt
    assert "fit_violations=不是服装本体" in prompt
    assert "主推荐：Obi's Battle Bikini" in answer
    assert "辅助参考：Cat Girl Amira Follower" in answer


@pytest.mark.asyncio
async def test_answer_matches_repairs_misleading_summary_when_support_context_exists(monkeypatch):
    class FakeClient:
        async def chat(self, prompt, model, max_tokens=1024):  # noqa: ARG002
            return (
                "主推荐：Direct Clothing。\n\n"
                "辅助参考（非主推荐）：Support Follower。\n\n"
                "以上结果严格遵循“只看R18女性服装”的需求，未包含非直接匹配内容。"
            )

    monkeypatch.setattr(answer_service_module, "create_llm_client", lambda **kwargs: FakeClient())  # noqa: ARG005

    answer = await AgentAnswerService().answer_matches(
        query="只看R18女性服装",
        matches=[_match("Direct Clothing"), _match("Support Follower").model_copy(update={"id": 2})],
        provider="test",
        api_key="key",
        base_url="",
        model="model",
        history=[],
        query_plan={
            "_agent_candidate_semantic_judge": {
                "fit_counts": {"direct_match": 1, "support_context": 1, "off_scope": 0, "uncertain": 0},
                "judgements": [
                    {"candidate_id": 1, "fit_type": "direct_match"},
                    {"candidate_id": 2, "fit_type": "support_context"},
                ],
            },
        },
    )

    assert "未包含非直接匹配内容" not in answer
    assert "主推荐符合本轮目标；辅助参考仅用于搭配说明，不作为主结果。" in answer


@pytest.mark.asyncio
async def test_answer_matches_appends_uncertain_notice_when_llm_omits_it(monkeypatch):
    class FakeClient:
        async def chat(self, prompt, model, max_tokens=1024):  # noqa: ARG002
            return "主推荐：VR UI Fixes。"

    monkeypatch.setattr(answer_service_module, "create_llm_client", lambda **kwargs: FakeClient())  # noqa: ARG005

    answer = await AgentAnswerService().answer_matches(
        query="只看 VR 兼容 UI",
        matches=[_match("VR UI Fixes"), _match("SSE Only HUD").model_copy(update={"id": 2})],
        provider="test",
        api_key="key",
        base_url="",
        model="model",
        history=[],
        query_plan={
            "_agent_candidate_semantic_judge": {
                "fit_counts": {"direct_match": 1, "support_context": 0, "off_scope": 0, "uncertain": 1},
                "judgements": [
                    {"candidate_id": 1, "fit_type": "direct_match"},
                    {"candidate_id": 2, "fit_type": "uncertain"},
                ],
            },
        },
    )

    assert "证据不足/待确认" in answer
    assert "不作为主推荐" in answer


@pytest.mark.asyncio
async def test_answer_generation_contract_fallback_separates_support_items():
    direct = _match("Direct Clothing")
    support = _match("Body Support")
    support = support.model_copy(update={"id": 2})

    output = await AnswerGenerationTool().run(
        AnswerGenerationInput(
            query="只看某类主结果",
            query_plan={
                "_agent_semantic_strategy": {
                    "user_goal": "只看某类主结果",
                    "answer_policy": {"main_results": "only_direct_match"},
                },
                "_agent_candidate_semantic_judge": {
                    "judgements": [
                        {"candidate_id": direct.id, "fit_type": "direct_match"},
                        {"candidate_id": support.id, "fit_type": "support_context"},
                    ]
                },
            },
            matches=[support, direct],
            llm_available=False,
        )
    )

    assert output.used_llm is False
    assert "直接符合本轮目标的结果" in output.answer
    assert "辅助上下文，不作为主结果" in output.answer
    assert output.answer.index("Direct Clothing") < output.answer.index("Body Support")


def test_parse_next_steps_drops_truncated_json_array_line():
    assert parse_next_steps('["这个 MOD 有哪些安装风险？') == []

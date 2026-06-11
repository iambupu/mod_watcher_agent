import pytest

from app.services.agent.schemas import AgentModMatch
from app.services.agent.tools.candidate_ranking_tool import (
    CandidateRankingInput,
    CandidateRankingTool,
)
from app.services.agent.tools.candidate_recovery_tool import (
    CandidateRecoveryOutput,
    CandidateRecoveryTool,
)
from app.services.agent.tools.match_materializer_tool import (
    MatchMaterializerOutput,
    MatchMaterializerTool,
)
from app.services.agent.tools.result_fusion_ranker_tool import (
    ResultFusionRankerOutput,
    ResultFusionRankerTool,
)


def _match(title: str) -> AgentModMatch:
    mod_id = sum(ord(ch) for ch in title) % 10000
    return AgentModMatch(
        id=mod_id,
        title=title,
        source="nexusmods",
        game="Skyrim Special Edition",
        author=None,
        version=None,
        url="https://example.com/mod",
        updated_at_remote=None,
        score=2,
    )


@pytest.mark.asyncio
async def test_candidate_ranking_merges_evidence_and_recovers_when_validator_drops_matches(monkeypatch):
    captured = {}

    def fake_fusion_run(self, tool_input):
        captured["fusion_query"] = tool_input.query
        captured["fusion_evidence_id"] = tool_input.evidence_id
        captured["fusion_apply_distinctive_filter"] = tool_input.apply_distinctive_filter
        return ResultFusionRankerOutput(
            results=["ranked"],
            evidence=[{"fragment_id": "r_fusion_1", "stage": "final_ranking", "evidence_id": tool_input.evidence_id}],
        )

    def fake_materializer_run(self, tool_input):
        captured["materializer_results"] = tool_input.results
        captured["materializer_evidence_id"] = tool_input.evidence_id
        return MatchMaterializerOutput(matches=[_match("Initial Match")])

    async def fake_validator(**kwargs):
        captured["validator_query_plan"] = kwargs["query_plan"]
        return []

    async def fake_recovery_run(self, tool_input):
        captured["recovery_plan_keywords"] = tool_input.plan.keywords
        captured["recovery_evidence_id"] = tool_input.evidence_id
        return CandidateRecoveryOutput(
            matches=[_match("Recovered Match")],
            evidence=[
                {
                    "fragment_id": "r_candidate_recovery_1",
                    "stage": "candidate_recovery",
                    "evidence_id": tool_input.evidence_id,
                }
            ],
        )

    monkeypatch.setattr(ResultFusionRankerTool, "run", fake_fusion_run)
    monkeypatch.setattr(MatchMaterializerTool, "run", fake_materializer_run)
    monkeypatch.setattr(CandidateRecoveryTool, "run", fake_recovery_run)

    output = await CandidateRankingTool(session=object(), validator=fake_validator).run(
        CandidateRankingInput(
            query="有什么相关风格的mod",
            query_plan={
                "keywords": ["bimbo"],
                "open_discovery": False,
                "retrieval_mode": "filtered",
                "limit": 5,
                "evidence_id": "ev_rank",
            },
            prior_evidence=[{"fragment_id": "r_exec_1", "stage": "local_retrieval", "evidence_id": "ev_rank"}],
            llm_available=True,
        )
    )

    assert [match.title for match in output.matches] == ["Recovered Match"]
    assert output.match_count == 1
    assert output.validator_status == "succeeded"
    assert captured["fusion_query"] == "有什么相关风格的mod"
    assert captured["fusion_evidence_id"] == "ev_rank"
    assert captured["fusion_apply_distinctive_filter"] is True
    assert captured["materializer_results"] == ["ranked"]
    assert captured["materializer_evidence_id"] == "ev_rank"
    assert captured["validator_query_plan"]["keywords"] == ["bimbo"]
    assert captured["recovery_plan_keywords"] == ["bimbo"]
    assert captured["recovery_evidence_id"] == "ev_rank"
    assert [item["fragment_id"] for item in output.evidence] == [
        "r_exec_1",
        "r_fusion_1",
        "r_candidate_recovery_1",
    ]


@pytest.mark.asyncio
async def test_candidate_ranking_uses_semantic_judge_for_open_discovery(monkeypatch):
    captured = {}

    def fake_fusion_run(self, tool_input):
        captured["fusion_apply_distinctive_filter"] = tool_input.apply_distinctive_filter
        return ResultFusionRankerOutput(
            results=["ranked"],
            evidence=[{"fragment_id": "r_fusion_1", "stage": "final_ranking", "evidence_id": tool_input.evidence_id}],
        )

    roleplay = _match("Bimbo Roleplay Framework")
    outfit = _match("Bimbo Outfit Preset")
    off_topic = _match("Unrelated Armor")

    def fake_materializer_run(self, tool_input):
        captured["materializer_limit"] = tool_input.limit
        return MatchMaterializerOutput(matches=[off_topic, outfit, roleplay])

    async def fake_validator(**kwargs):
        raise AssertionError("open discovery should let semantic judge see materialized candidates first")

    async def fake_judge(tool_input):
        captured["judge_titles"] = [item.title for item in tool_input.candidates]
        return {
            "judgements": [
                {
                    "candidate_id": roleplay.id,
                    "relevance": "high",
                    "fit_type": "direct_match",
                    "group": "core_gameplay",
                    "reason": "direct roleplay mechanics",
                },
                {
                    "candidate_id": outfit.id,
                    "relevance": "medium",
                    "fit_type": "support_context",
                    "group": "visual_support",
                    "reason": "supporting visual style",
                    "violations": ["support_only"],
                },
                {
                    "candidate_id": off_topic.id,
                    "relevance": "reject",
                    "fit_type": "off_scope",
                    "group": "off_topic",
                    "reason": "not bimbo roleplay",
                },
            ],
            "groups": [
                {
                    "name": "core_gameplay",
                    "label": "核心玩法",
                    "candidate_ids": [roleplay.id],
                    "reason": "main mechanics",
                },
                {
                    "name": "visual_support",
                    "label": "外观配套",
                    "candidate_ids": [outfit.id],
                    "reason": "style support",
                },
            ],
            "gaps": ["缺少安装风险证据"],
            "rejected": [{"candidate_id": off_topic.id, "reason": "not relevant"}],
        }

    monkeypatch.setattr(ResultFusionRankerTool, "run", fake_fusion_run)
    monkeypatch.setattr(MatchMaterializerTool, "run", fake_materializer_run)

    output = await CandidateRankingTool(
        session=object(),
        validator=fake_validator,
        semantic_judge=fake_judge,
    ).run(
        CandidateRankingInput(
            query="天际有什么扮演 bimbo 的 MOD",
            query_plan={
                "keywords": ["bimbo"],
                "open_discovery": True,
                "retrieval_mode": "fuzzy",
                "_agent_semantic_strategy": {
                    "task_type": "open_discovery",
                    "strategy": "broad_then_judge",
                },
                "limit": 5,
                "candidate_pool_limit": 30,
                "evidence_id": "ev_rank",
            },
            prior_evidence=[{"fragment_id": "r_exec_1", "stage": "local_retrieval", "evidence_id": "ev_rank"}],
            llm_available=True,
        )
    )

    assert [match.title for match in output.matches] == ["Bimbo Roleplay Framework", "Bimbo Outfit Preset"]
    assert output.semantic_judge_status == "succeeded"
    assert captured["fusion_apply_distinctive_filter"] is False
    assert captured["materializer_limit"] == 30
    assert captured["judge_titles"] == ["Unrelated Armor", "Bimbo Outfit Preset", "Bimbo Roleplay Framework"]
    assert output.query_plan["_agent_candidate_semantic_judge"]["groups"][0]["label"] == "核心玩法"
    assert output.query_plan["_agent_candidate_semantic_judge"]["fit_counts"]["direct_match"] == 1
    assert output.query_plan["_agent_candidate_semantic_judge"]["fit_counts"]["support_context"] == 1
    assert "语义裁判：high / 直接命中 / 核心玩法" in output.matches[0].rank_reason
    assert "违例：support_only" in output.matches[1].rank_reason
    assert [item["fragment_id"] for item in output.evidence] == [
        "r_exec_1",
        "r_fusion_1",
        "r_candidate_semantic_judge_1",
    ]
    judge_evidence = output.evidence[-1]
    assert judge_evidence["used_llm"] is True
    assert judge_evidence["rejected_count"] == 1


@pytest.mark.asyncio
async def test_candidate_ranking_judges_pool_then_trims_to_display_limit(monkeypatch):
    captured = {}
    candidates = [_match(f"Candidate {index}") for index in range(1, 9)]

    def fake_fusion_run(self, tool_input):
        return ResultFusionRankerOutput(
            results=["ranked"],
            evidence=[{"fragment_id": "r_fusion_1", "stage": "final_ranking", "evidence_id": tool_input.evidence_id}],
        )

    def fake_materializer_run(self, tool_input):
        captured["materializer_limit"] = tool_input.limit
        return MatchMaterializerOutput(matches=candidates)

    async def fake_validator(**kwargs):
        raise AssertionError("semantic judge should run before deterministic validator for open discovery")

    async def fake_judge(tool_input):
        captured["judge_count"] = len(tool_input.candidates)
        return {
            "judgements": [
                {"candidate_id": item.id, "relevance": "high", "fit_type": "direct_match", "group": "core_gameplay", "reason": f"rank {index}"}
                for index, item in enumerate(reversed(candidates), start=1)
            ],
            "groups": [{"name": "core_gameplay", "label": "核心玩法", "candidate_ids": [item.id for item in candidates], "reason": "pool"}],
            "gaps": [],
            "rejected": [],
        }

    monkeypatch.setattr(ResultFusionRankerTool, "run", fake_fusion_run)
    monkeypatch.setattr(MatchMaterializerTool, "run", fake_materializer_run)

    output = await CandidateRankingTool(
        session=object(),
        validator=fake_validator,
        semantic_judge=fake_judge,
    ).run(
        CandidateRankingInput(
            query="天际有什么 bimbo MOD",
            query_plan={
                "keywords": ["bimbo"],
                "open_discovery": True,
                "retrieval_mode": "fuzzy",
                "limit": 3,
                "candidate_pool_limit": 8,
                "evidence_id": "ev_pool",
            },
            llm_available=True,
        )
    )

    assert captured["materializer_limit"] == 8
    assert captured["judge_count"] == 8
    assert len(output.matches) == 3
    assert output.evidence[-1]["input_count"] == 8
    assert output.evidence[-1]["output_count"] == 3


@pytest.mark.asyncio
async def test_candidate_ranking_orders_by_fit_type_and_removes_off_scope(monkeypatch):
    direct = _match("Direct Match")
    support = _match("Support Context")
    uncertain = _match("Uncertain Match")
    off_scope = _match("Off Scope")

    def fake_fusion_run(self, tool_input):
        return ResultFusionRankerOutput(results=["ranked"], evidence=[])

    def fake_materializer_run(self, tool_input):
        return MatchMaterializerOutput(matches=[support, off_scope, uncertain, direct])

    async def fake_validator(**kwargs):
        raise AssertionError("semantic judge should own open discovery filtering")

    async def fake_judge(tool_input):
        return {
            "judgements": [
                {"candidate_id": support.id, "relevance": "high", "fit_type": "support_context", "group": "related_addon", "reason": "support"},
                {"candidate_id": off_scope.id, "relevance": "medium", "fit_type": "off_scope", "group": "off_topic", "reason": "off"},
                {"candidate_id": uncertain.id, "relevance": "high", "fit_type": "uncertain", "group": "other_related", "reason": "uncertain"},
                {"candidate_id": direct.id, "relevance": "low", "fit_type": "direct_match", "group": "other_related", "reason": "direct"},
            ],
            "groups": [],
            "gaps": [],
            "rejected": [],
        }

    monkeypatch.setattr(ResultFusionRankerTool, "run", fake_fusion_run)
    monkeypatch.setattr(MatchMaterializerTool, "run", fake_materializer_run)

    output = await CandidateRankingTool(
        session=object(),
        validator=fake_validator,
        semantic_judge=fake_judge,
    ).run(
        CandidateRankingInput(
            query="只看某类主结果",
            query_plan={"open_discovery": True, "retrieval_mode": "fuzzy", "limit": 8},
            llm_available=True,
        )
    )

    assert [match.title for match in output.matches] == ["Direct Match", "Support Context", "Uncertain Match"]
    assert output.query_plan["_agent_candidate_semantic_judge"]["fit_counts"]["off_scope"] == 1


@pytest.mark.asyncio
async def test_candidate_ranking_preserves_category_semantic_compatibility(monkeypatch):
    bikini = _match("A sexy straps bikini for UNP")
    bikini = bikini.model_copy(update={"category": "Armour", "adult_content": True})

    def fake_fusion_run(self, tool_input):
        return ResultFusionRankerOutput(results=["ranked"], evidence=[])

    def fake_materializer_run(self, tool_input):
        return MatchMaterializerOutput(matches=[bikini])

    async def fake_validator(**kwargs):
        raise AssertionError("semantic judge should own open discovery filtering")

    async def fake_judge(tool_input):
        return {
            "judgements": [
                {
                    "candidate_id": bikini.id,
                    "relevance": "high",
                    "fit_type": "direct_match",
                    "group": "visual_support",
                    "category_semantic_compatibility": "compatible",
                    "category_compatibility_reason": "Armour category contains bikini wearable clothing evidence.",
                    "reason": "adult bikini wearable",
                    "evidence": ["title contains bikini"],
                    "violations": [],
                }
            ],
            "groups": [],
            "gaps": [],
            "rejected": [],
        }

    monkeypatch.setattr(ResultFusionRankerTool, "run", fake_fusion_run)
    monkeypatch.setattr(MatchMaterializerTool, "run", fake_materializer_run)

    output = await CandidateRankingTool(
        session=object(),
        validator=fake_validator,
        semantic_judge=fake_judge,
    ).run(
        CandidateRankingInput(
            query="只看天际的R18女性服装",
            query_plan={"open_discovery": True, "retrieval_mode": "fuzzy", "limit": 8},
            llm_available=True,
        )
    )

    assert [match.title for match in output.matches] == ["A sexy straps bikini for UNP"]
    assert "分类语义：兼容" in output.matches[0].rank_reason
    assert "分类依据：Armour category contains bikini wearable clothing evidence." in output.matches[0].rank_reason
    summary = output.query_plan["_agent_candidate_semantic_judge"]
    assert summary["category_compatibility_counts"]["compatible"] == 1
    assert summary["judgements"][0]["category_semantic_compatibility"] == "compatible"
    assert output.evidence[-1]["category_compatibility_counts"]["compatible"] == 1


@pytest.mark.asyncio
async def test_candidate_ranking_uses_semantic_judge_for_filtered_contract(monkeypatch):
    bikini = _match("Obi's Battle Bikini 4K 3BA BHUNP UBE")
    bikini = bikini.model_copy(update={"category": "Armour", "adult_content": True})
    captured = {}

    def fake_fusion_run(self, tool_input):
        return ResultFusionRankerOutput(results=["ranked"], evidence=[])

    def fake_materializer_run(self, tool_input):
        captured["materializer_limit"] = tool_input.limit
        return MatchMaterializerOutput(matches=[bikini])

    async def fake_validator(**kwargs):
        return kwargs["matches"]

    async def fake_judge(tool_input):
        captured["judge_query"] = tool_input.query
        captured["judge_strategy"] = tool_input.semantic_strategy
        return {
            "judgements": [
                {
                    "candidate_id": bikini.id,
                    "relevance": "high",
                    "fit_type": "direct_match",
                    "group": "visual_support",
                    "category_semantic_compatibility": "compatible",
                    "category_compatibility_reason": "Armour source category is compatible with bikini clothing intent.",
                    "reason": "R18 bikini outfit is wearable female clothing",
                }
            ],
            "groups": [],
            "gaps": [],
            "rejected": [],
        }

    monkeypatch.setattr(ResultFusionRankerTool, "run", fake_fusion_run)
    monkeypatch.setattr(MatchMaterializerTool, "run", fake_materializer_run)

    output = await CandidateRankingTool(
        session=object(),
        validator=fake_validator,
        semantic_judge=fake_judge,
    ).run(
        CandidateRankingInput(
            query="只看天际的R18女性服装",
            query_plan={
                "open_discovery": False,
                "retrieval_mode": "filtered",
                "limit": 8,
                "_agent_semantic_strategy": {
                    "direct_match_definition": ["R18 Skyrim female clothing or outfit wearable items"],
                    "answer_policy": {"main_results": "ranked_by_fit_type"},
                },
            },
            llm_available=True,
        )
    )

    assert captured["materializer_limit"] == 8
    assert captured["judge_query"] == "只看天际的R18女性服装"
    assert captured["judge_strategy"]["direct_match_definition"] == ["R18 Skyrim female clothing or outfit wearable items"]
    assert [match.title for match in output.matches] == ["Obi's Battle Bikini 4K 3BA BHUNP UBE"]
    assert output.semantic_judge_status == "succeeded"
    assert output.query_plan["_agent_candidate_semantic_judge"]["category_compatibility_counts"]["compatible"] == 1


@pytest.mark.asyncio
async def test_candidate_ranking_hides_non_direct_matches_for_direct_only_contract(monkeypatch):
    support = _match("Support Context")
    uncertain = _match("Uncertain Match")

    def fake_fusion_run(self, tool_input):
        return ResultFusionRankerOutput(results=["ranked"], evidence=[])

    def fake_materializer_run(self, tool_input):
        return MatchMaterializerOutput(matches=[support, uncertain])

    async def fake_validator(**kwargs):
        raise AssertionError("semantic judge should own open discovery filtering")

    async def fake_judge(tool_input):
        return {
            "judgements": [
                {
                    "candidate_id": support.id,
                    "relevance": "medium",
                    "fit_type": "support_context",
                    "group": "related_addon",
                    "reason": "support only",
                },
                {
                    "candidate_id": uncertain.id,
                    "relevance": "low",
                    "fit_type": "uncertain",
                    "group": "other_related",
                    "reason": "not enough evidence",
                },
            ],
            "groups": [],
            "gaps": ["没有直接命中项"],
            "rejected": [],
        }

    async def fake_recovery_run(self, tool_input):  # pragma: no cover - must not be called
        raise AssertionError("direct-only semantic empty result should not recover weak candidates")

    monkeypatch.setattr(ResultFusionRankerTool, "run", fake_fusion_run)
    monkeypatch.setattr(MatchMaterializerTool, "run", fake_materializer_run)
    monkeypatch.setattr(CandidateRecoveryTool, "run", fake_recovery_run)

    output = await CandidateRankingTool(
        session=object(),
        validator=fake_validator,
        semantic_judge=fake_judge,
    ).run(
        CandidateRankingInput(
            query="只看某类主结果",
            query_plan={
                "open_discovery": True,
                "retrieval_mode": "fuzzy",
                "limit": 8,
                "_agent_semantic_strategy": {
                    "answer_policy": {
                        "main_results": "only_direct_match",
                    }
                },
            },
            llm_available=True,
        )
    )

    assert output.matches == []
    assert output.match_count == 0
    assert output.evidence[-1]["output_count"] == 0
    assert output.query_plan["_agent_candidate_semantic_judge"]["fit_counts"]["direct_match"] == 0
    assert output.query_plan["_agent_candidate_semantic_judge"]["fit_counts"]["support_context"] == 1
    assert output.query_plan["_agent_candidate_semantic_judge"]["fit_counts"]["uncertain"] == 1


@pytest.mark.asyncio
async def test_candidate_ranking_keeps_existing_path_when_llm_unavailable(monkeypatch):
    def fake_fusion_run(self, tool_input):
        return ResultFusionRankerOutput(results=["ranked"], evidence=[])

    def fake_materializer_run(self, tool_input):
        return MatchMaterializerOutput(matches=[_match("Original Match")])

    async def fake_validator(**kwargs):
        return kwargs["matches"]

    async def fake_judge(tool_input):  # pragma: no cover - must not be called
        raise AssertionError("semantic judge should not run without llm")

    monkeypatch.setattr(ResultFusionRankerTool, "run", fake_fusion_run)
    monkeypatch.setattr(MatchMaterializerTool, "run", fake_materializer_run)

    output = await CandidateRankingTool(
        session=object(),
        validator=fake_validator,
        semantic_judge=fake_judge,
    ).run(
        CandidateRankingInput(
            query="天际有什么扮演 bimbo 的 MOD",
            query_plan={"open_discovery": True, "retrieval_mode": "fuzzy", "limit": 5},
            llm_available=False,
        )
    )

    assert [match.title for match in output.matches] == ["Original Match"]
    assert output.semantic_judge_status == "skipped"
    assert "_agent_candidate_semantic_judge" not in output.query_plan


@pytest.mark.asyncio
async def test_candidate_ranking_skips_semantic_judge_when_validator_drops_filtered_candidates(monkeypatch):
    bikini = _match("A sexy straps bikini for UNP")

    def fake_fusion_run(self, tool_input):
        return ResultFusionRankerOutput(results=["ranked"], evidence=[])

    def fake_materializer_run(self, tool_input):
        return MatchMaterializerOutput(matches=[bikini])

    async def fake_validator(**kwargs):
        return []

    async def fake_judge(tool_input):  # pragma: no cover - must not be called
        raise AssertionError("semantic judge should not run after validator removes all candidates")

    async def fake_recovery_run(self, tool_input):  # pragma: no cover - must not be called
        raise AssertionError("direct-only empty result should not recover weak candidates")

    monkeypatch.setattr(ResultFusionRankerTool, "run", fake_fusion_run)
    monkeypatch.setattr(MatchMaterializerTool, "run", fake_materializer_run)
    monkeypatch.setattr(CandidateRecoveryTool, "run", fake_recovery_run)

    output = await CandidateRankingTool(
        session=object(),
        validator=fake_validator,
        semantic_judge=fake_judge,
    ).run(
        CandidateRankingInput(
            query="只看天际的R18女性服装",
            query_plan={
                "open_discovery": False,
                "retrieval_mode": "filtered",
                "limit": 8,
                "_agent_semantic_strategy": {
                    "direct_match_definition": ["R18 Skyrim female clothing"],
                    "answer_policy": {"main_results": "only_direct_match"},
                },
            },
            llm_available=True,
        )
    )

    assert output.matches == []
    assert output.semantic_judge_status == "skipped"
    assert "_agent_candidate_semantic_judge" not in output.query_plan

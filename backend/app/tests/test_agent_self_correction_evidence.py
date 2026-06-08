from app.services.agent.schemas import AgentModMatch
from app.services.agent.self_correction.self_correction_evidence import (
    build_self_correction_evidence,
)


def _match(mod_id: int, title: str, summary: str = "") -> AgentModMatch:
    return AgentModMatch(
        id=mod_id,
        title=title,
        source="nexusmods",
        game="Skyrim Special Edition",
        category="Clothing",
        author="Author",
        version=None,
        url=f"https://example.com/{mod_id}",
        updated_at_remote=None,
        score=100 - mod_id,
        original_summary=summary,
    )


def test_build_self_correction_evidence_uses_contract_and_judge_summary():
    evidence = build_self_correction_evidence(
        original_query="只看天际的女性服装",
        query_plan={
            "games": ["skyrimspecialedition"],
            "adult_content": True,
            "_agent_semantic_strategy": {
                "user_goal": "只看女性服装",
                "direct_match_definition": ["候选本体必须是服装"],
                "support_context_definition": ["身体和随从只能辅助"],
                "reject_as_primary": ["follower_only"],
            },
            "_agent_candidate_semantic_judge": {
                "fit_counts": {"direct_match": 1, "support_context": 1, "uncertain": 0, "off_scope": 0},
                "gaps": ["直接命中数量不足"],
                "judgements": [
                    {
                        "candidate_id": 1,
                        "fit_type": "direct_match",
                        "evidence": ["标题包含 outfit"],
                        "violations": [],
                    },
                    {
                        "candidate_id": 2,
                        "fit_type": "support_context",
                        "evidence": ["随从只能辅助"],
                        "violations": ["不是服装本体"],
                    },
                ],
            },
        },
        matches=[
            _match(1, "Elegant Outfit", "A female outfit with dress."),
            _match(2, "Follower Preset", "A standalone follower."),
        ],
        retrieval_evidence={"mode": "local_plus_web", "oversized": "x" * 600},
        history_summary="历史只作参考",
    )

    assert evidence.current_goal == "只看女性服装"
    assert evidence.hard_constraints == {"games": ["skyrimspecialedition"], "adult_content": True}
    assert evidence.direct_match_definition == ["候选本体必须是服装"]
    assert evidence.support_context_definition == ["身体和随从只能辅助"]
    assert evidence.reject_as_primary == ["follower_only"]
    assert evidence.fit_counts["direct_match"] == 1
    assert evidence.gaps == ["直接命中数量不足"]
    assert evidence.candidate_snapshot[0].fit_type == "direct_match"
    assert evidence.candidate_snapshot[1].violations == ["不是服装本体"]
    assert evidence.retrieval_summary == {"mode": "local_plus_web"}
    assert evidence.history_summary == "历史只作参考"


def test_build_self_correction_evidence_bounds_candidate_snapshot_and_text():
    matches = [_match(index, f"Mod {index}", "x" * 500) for index in range(1, 25)]

    evidence = build_self_correction_evidence(
        original_query="query",
        query_plan={
            "_agent_semantic_strategy": {"user_goal": "goal"},
            "_agent_candidate_semantic_judge": {},
        },
        matches=matches,
        retrieval_evidence={"mode": "local_only"},
    )

    assert len(evidence.candidate_snapshot) == 20
    assert len(evidence.candidate_snapshot[0].summary_snippet) == 260


def test_build_self_correction_evidence_uses_plural_hard_filter_fields():
    evidence = build_self_correction_evidence(
        original_query="只看 Nexus 的 Skyrim 女性服装",
        query_plan={
            "games": ["skyrimspecialedition"],
            "sources": ["nexusmods"],
            "_agent_semantic_strategy": {
                "hard_filters": {
                    "games": ["skyrimspecialedition"],
                    "sources": ["nexusmods"],
                    "categories": ["Clothing"],
                }
            },
        },
        matches=[],
    )

    assert evidence.hard_constraints == {
        "games": ["skyrimspecialedition"],
        "sources": ["nexusmods"],
        "categories": ["Clothing"],
    }


def test_build_self_correction_evidence_normalizes_legacy_hard_filter_aliases():
    evidence = build_self_correction_evidence(
        original_query="只看 Nexus 的 Skyrim 女性服装",
        query_plan={
            "_agent_semantic_strategy": {
                "hard_filters": {
                    "game": "Skyrim SE",
                    "source": "NexusMods",
                }
            },
        },
        matches=[],
    )

    assert evidence.hard_constraints == {
        "games": ["Skyrim SE"],
        "sources": ["NexusMods"],
    }

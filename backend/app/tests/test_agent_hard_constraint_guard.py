from app.services.agent.self_correction.hard_constraint_guard import guard_self_correction_plan
from app.services.agent.self_correction.self_correction_evidence import (
    SelfCorrectionCandidateSnapshot,
    SelfCorrectionEvidence,
)
from app.services.agent.self_correction.self_correction_schema import LLMSelfCorrectionReviewResult


def _evidence() -> SelfCorrectionEvidence:
    return SelfCorrectionEvidence(
        original_query="只看 Nexus 的 Skyrim 任务线 Mod",
        current_goal="只看任务线 Mod",
        hard_constraints={"games": ["skyrimspecialedition"], "sources": ["nexusmods"]},
        direct_match_definition=["必须是任务线"],
        candidate_snapshot=[
            SelfCorrectionCandidateSnapshot(
                id=1,
                title="Questline Direct",
                source="nexusmods",
                game="Skyrim Special Edition",
                fit_type="direct_match",
            ),
            SelfCorrectionCandidateSnapshot(
                id=2,
                title="Follower Support",
                source="nexusmods",
                game="Skyrim Special Edition",
                fit_type="support_context",
            ),
        ],
    )


def _review(correction_plan: dict) -> LLMSelfCorrectionReviewResult:
    return LLMSelfCorrectionReviewResult(
        action="refine_retrieval",
        reason_summary="需要修正",
        correction_plan=correction_plan,
        changed_fields=list(correction_plan),
        confidence=0.8,
    )


def test_hard_constraint_guard_allows_safe_correction_plan():
    result = guard_self_correction_plan(
        evidence=_evidence(),
        review_result=_review({"keywords": ["questline", "story"], "sources": ["nexusmods"]}),
    )

    assert result.passed is True
    assert result.repair_action == "allow"
    assert result.safe_correction_plan["keywords"] == ["questline", "story"]


def test_hard_constraint_guard_blocks_hard_constraint_removal():
    result = guard_self_correction_plan(
        evidence=_evidence(),
        review_result=_review({"remove_fields": ["sources"]}),
    )

    assert result.passed is False
    assert result.repair_action == "block"
    assert result.rejected_changes == ["cannot_remove_hard_constraint:sources"]


def test_hard_constraint_guard_blocks_legacy_alias_removal():
    result = guard_self_correction_plan(
        evidence=_evidence(),
        review_result=_review({"remove_fields": ["source"]}),
    )

    assert result.passed is False
    assert result.rejected_changes == ["cannot_remove_hard_constraint:sources"]


def test_hard_constraint_guard_blocks_hard_constraint_change():
    result = guard_self_correction_plan(
        evidence=_evidence(),
        review_result=_review({"query_plan": {"games": ["cyberpunk2077"], "sources": ["nexusmods"]}}),
    )

    assert result.passed is False
    assert result.repair_action == "block"
    assert result.rejected_changes == ["cannot_change_hard_constraint:games"]


def test_hard_constraint_guard_strips_support_title_from_core_terms():
    result = guard_self_correction_plan(
        evidence=_evidence(),
        review_result=_review({"keywords": ["questline", "Follower Support"], "query_plan": {"core_terms": ["Follower Support"]}}),
    )

    assert result.passed is True
    assert result.repair_action == "strip_unsafe_changes"
    assert result.safe_correction_plan["keywords"] == ["questline"]
    assert result.safe_correction_plan["query_plan"]["core_terms"] == []
    assert result.rejected_changes == [
        "removed_non_primary_title_from_keywords:Follower Support",
        "removed_non_primary_title_from_core_terms:Follower Support",
    ]

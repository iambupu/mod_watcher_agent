from app.services.agent.context.context_inference import (
    followup_decision,
    semantic_continuity_score,
    should_inherit_context_keywords,
)
from app.services.agent.semantic_search import canonical_semantic_terms


def test_followup_decision_is_low_for_strong_new_topic():
    decision = followup_decision("有什么 cyberpunk 2077 的载具改装 mod")
    assert decision.is_followup is False
    assert decision.score < 0.55


def test_followup_decision_is_high_for_low_signal_similarity_followup():
    decision = followup_decision("有什么相关风格的mod")
    assert decision.is_followup is True
    assert decision.score >= 0.55
    assert "low_signal_query" in decision.reasons


def test_should_not_inherit_when_current_has_distinctive_keywords():
    inherit = should_inherit_context_keywords(
        "有什么 bimbo 相关的",
        ["bimbo"],
        ["cbbe"],
    )
    assert inherit is False


def test_should_inherit_when_followup_has_distinctive_overlap_with_context():
    inherit = should_inherit_context_keywords(
        "继续找 bimbo 同类",
        ["bimbo"],
        ["bimbo", "body"],
    )
    assert inherit is True


def test_semantic_continuity_score_is_low_for_topic_break():
    score = semantic_continuity_score(
        "有什么 cyberpunk 载具 mod",
        ["cyberpunk", "vehicle"],
        ["bimbo", "body"],
    )
    assert score < 0.3


def test_semantic_continuity_score_uses_semantic_normalization_aliases():
    score = semantic_continuity_score(
        "有什么妓女风格的服装mod",
        ["妓女", "服装"],
        ["prostitute", "outfit"],
    )
    assert score > 0.3


def test_semantic_continuity_reuses_shared_semantic_aliases():
    assert canonical_semantic_terms(["怀孕", "pregnant", "体系", "system", "服装", "outfit"]) == [
        "pregnancy",
        "framework",
        "outfit",
    ]

    pregnancy_score = semantic_continuity_score(
        "继续找怀孕玩法",
        ["怀孕", "玩法"],
        ["pregnancy", "gameplay"],
    )
    framework_score = semantic_continuity_score(
        "继续找爱的实验室体系mod",
        ["爱的实验室", "体系"],
        ["loverslab", "framework"],
    )

    assert pregnancy_score >= 0.5
    assert framework_score >= 0.5

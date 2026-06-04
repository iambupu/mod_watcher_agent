from app.services.agent.context.context_inference import (
    decide_context_inheritance,
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


def test_followup_decision_tracks_common_followup_phrases():
    for query in ["还有类似的吗", "有什么相关风格的mod", "继续这个方向"]:
        decision = followup_decision(query)
        assert decision.is_followup is True
        assert decision.low_signal is True


def test_followup_decision_treats_source_refine_similar_results_as_low_signal():
    decision = followup_decision("只看 LL 的类似结果")

    assert decision.is_followup is True
    assert decision.low_signal is True
    assert "has_relational_intent" in decision.reasons


def test_context_inheritance_allows_source_refine_with_weak_current_terms():
    decision = decide_context_inheritance(
        query="只看 LL 的类似结果",
        current_keywords=["ll", "的结果"],
        context_keywords=["bimbo"],
        context_quality=0.55,
        has_refinement_constraints=True,
        context_has_semantic_anchors=True,
    )

    assert decision.inherit_keywords is True
    assert decision.topic_shift is False
    assert "refinement_bias" in decision.policy_reasons


def test_followup_decision_suppresses_new_strong_topic_even_with_switch_word():
    decision = followup_decision("换成 Skyrim 的正常服装 mod")

    assert decision.is_followup is False
    assert decision.low_signal is False


def test_should_not_inherit_when_current_has_distinctive_keywords():
    inherit = should_inherit_context_keywords(
        "有什么 bimbo 相关的",
        ["bimbo"],
        ["cbbe"],
    )
    assert inherit is False


def test_should_not_inherit_adult_gameplay_context_into_normal_outfit_query():
    inherit = should_inherit_context_keywords(
        "换成 Skyrim 的正常服装 mod",
        ["skyrim", "outfit"],
        ["bimbo", "pregnancy"],
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

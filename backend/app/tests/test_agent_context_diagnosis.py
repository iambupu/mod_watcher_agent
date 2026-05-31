from app.services.agent.planning.context_diagnosis import (
    decide_preference_memory_gate,
    evaluate_context_diagnosis,
)


def test_context_diagnosis_promotes_semantic_followup_without_keywords():
    signal = evaluate_context_diagnosis(
        query="继续找相关的",
        known_slots={},
        context_keywords=[],
        context_slots={
            "semantic_anchors": ["pregnancy", "gameplay"],
            "source": "recent_user",
            "quality_score": 0.4,
        },
    )

    assert signal.followup.is_followup is True
    assert signal.context_semantic_anchors == ["pregnancy", "gameplay"]
    assert signal.effective_context_terms == ["pregnancy", "gameplay"]
    assert signal.inherit_score > 0.0
    assert signal.topic_shift is False


def test_context_diagnosis_marks_topic_shift_on_game_conflict():
    signal = evaluate_context_diagnosis(
        query="cyberpunk vehicle overhaul mod",
        known_slots={"game": "Cyberpunk 2077"},
        context_keywords=["vehicle", "overhaul"],
        context_slots={"game": "Skyrim Special Edition"},
    )

    assert signal.topic_shift is True
    assert signal.continuity_score <= 0.15
    assert signal.inherit_score <= 0.15


def test_context_diagnosis_tolerates_invalid_quality_score():
    signal = evaluate_context_diagnosis(
        query="继续找相关的",
        known_slots={},
        context_keywords=["bimbo"],
        context_slots={"quality_score": "bad"},
    )

    assert signal.context_quality_score == 0.0


def test_preference_gate_uses_llm_semantic_anchors_as_current_signal():
    gate = decide_preference_memory_gate(
        query="这个短语本地语义表不认识",
        query_plan={
            "intent": "search",
            "keywords": [],
            "games": [],
            "sources": [],
        },
        context_keywords=[],
        context_slots={},
        preferences={
            "favorite_summary": {
                "top_games": ["Skyrim Special Edition"],
                "top_sources": ["nexusmods"],
            }
        },
        semantic_anchors=["custom_llm_anchor", "custom_llm_domain"],
    )

    assert gate.allow is False
    assert gate.reason == "strong_current_signal"


def test_preference_gate_locks_to_recent_context_before_favorites():
    gate = decide_preference_memory_gate(
        query="继续找相关的",
        query_plan={
            "intent": "search",
            "keywords": [],
            "games": [],
            "sources": [],
        },
        context_keywords=["bimbo"],
        context_slots={"semantic_anchors": ["bimbo"], "source": "recent_user", "quality_score": 0.4},
        preferences={
            "favorite_summary": {
                "top_games": ["Stellar Blade"],
                "top_sources": ["nexusmods"],
            }
        },
        semantic_anchors=[],
    )

    assert gate.allow is False
    assert gate.reason == "context_locked"

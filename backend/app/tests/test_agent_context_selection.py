from app.services.agent.context.context_selection import (
    context_quality_score,
    select_history_query_context,
    should_inherit_active_constraints,
    should_use_current_query_context,
)


def test_should_use_current_query_context_for_strong_new_topic():
    current_keywords = ["cyberpunk", "vehicle", "overhaul"]

    assert should_use_current_query_context("cyberpunk vehicle overhaul mod", current_keywords) is True
    assert should_inherit_active_constraints("cyberpunk vehicle overhaul mod") is False


def test_should_inherit_active_constraints_for_low_signal_followup():
    assert should_inherit_active_constraints("有什么相关风格的mod") is True


def test_select_history_query_context_prefers_semantic_continuity_and_quality():
    selection = select_history_query_context(
        current_text="继续找 bimbo 同类",
        current_keywords=["bimbo"],
        candidates=[
            {"source": "recent_user", "keywords": ["vehicle"], "game": "Cyberpunk 2077"},
            {
                "source": "recent_user",
                "keywords": ["bimbo", "body"],
                "semantic_anchors": ["roleplay"],
                "game": "Skyrim Special Edition",
            },
        ],
    )

    assert selection is not None
    assert selection.selected_context["keywords"] == ["bimbo", "body"]
    assert selection.selected_context["quality_score"] == context_quality_score(selection.selected_context)
    assert "has_relational_intent" in selection.followup.reasons
    assert selection.score > 0.0


def test_select_history_query_context_rejects_weak_unrelated_context():
    selection = select_history_query_context(
        current_text="cyberpunk vehicle overhaul mod",
        current_keywords=["cyberpunk", "vehicle", "overhaul"],
        candidates=[{"source": "recent_user", "keywords": ["bimbo"]}],
    )

    assert selection is None

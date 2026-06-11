# 中文注释：说明 backend/app/tests/test_agent_context_active_constraints.py 的模块职责，便于后续维护定位。

from app.services.agent.planning.context_active_constraints import apply_active_constraints


def test_apply_active_constraints_fills_only_missing_scope_slots():
    raw = {"keywords": ["bimbo"], "games": [], "sources": ["loverslab"], "adult_content": None}

    apply_active_constraints(
        raw,
        {
            "game": "Skyrim Special Edition",
            "source": "nexusmods",
            "adult_content": True,
            "sort_field": "updated_at_remote",
        },
    )

    assert raw["games"] == ["Skyrim Special Edition"]
    assert raw["sources"] == ["loverslab"]
    assert raw["adult_content"] is True
    assert raw["sort_field"] == "updated_at_remote"


def test_apply_active_constraints_preserves_current_boolean_override():
    raw = {"adult_content": False, "sort_field": "relevance"}

    apply_active_constraints(raw, {"adult_content": True, "sort_field": "updated_at_remote"})

    assert raw["adult_content"] is False
    assert raw["sort_field"] == "relevance"

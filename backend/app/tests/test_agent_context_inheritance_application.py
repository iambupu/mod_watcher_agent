from app.services.agent.planning.context_inheritance_application import (
    apply_followup_context,
    has_refinement_constraints,
    merge_context_keywords,
)


def test_apply_followup_context_records_signal_and_inherits_keywords(caplog):
    raw = {"keywords": ["related"], "games": [], "sources": [], "categories": []}
    context = {
        "source": "recent_user",
        "keywords": ["bimbo", "roleplay"],
        "semantic_anchors": ["roleplay"],
        "game": "Skyrim Special Edition",
        "source_name": "loverslab",
        "quality_score": 0.82,
    }

    with caplog.at_level("INFO"):
        apply_followup_context(raw, context, "继续找相关的")

    assert raw["keywords"][:2] == ["bimbo", "roleplay"]
    assert raw["games"] == ["Skyrim Special Edition"]
    assert raw["sources"] == ["loverslab"]
    assert raw["_agent_context_hint"]["game"] == "Skyrim Special Edition"
    assert raw["_agent_context_hint"]["source_name"] == "loverslab"
    signal = raw["_agent_context_signal"]
    assert signal["source"] == "recent_user"
    assert signal["inherited"] is True
    assert signal["inherit_mode"] == "fallback_keywords"
    assert signal["primary_keywords"] == ["related"]
    assert signal["fallback_keywords"][:2] == ["bimbo", "roleplay"]
    assert signal["keyword_source"] == "fallback_from_context"
    assert signal["skipped_reason"] == ""
    assert signal["overridden_by_current_signal"] is False
    assert {"keywords", "games", "sources"}.issubset(set(signal["inherited_fields"]))
    assert signal["inherit_score"] >= 0.0
    assert any(
        "agent.context_inherit" in item.message
        and "inherited=True" in item.message
        and "inherited_fields=" in item.message
        for item in caplog.records
    )


def test_apply_followup_context_preserves_explicit_slots():
    raw = {
        "keywords": ["vehicle", "overhaul"],
        "games": ["Cyberpunk 2077"],
        "sources": ["nexusmods"],
        "categories": [],
        "adult_content": False,
    }
    context = {
        "source": "recent_user",
        "keywords": ["bimbo"],
        "game": "Skyrim Special Edition",
        "source_name": "loverslab",
        "adult_content": True,
        "quality_score": 0.8,
    }

    apply_followup_context(raw, context, "cyberpunk vehicle overhaul mod")

    assert raw["games"] == ["Cyberpunk 2077"]
    assert raw["sources"] == ["nexusmods"]
    assert raw["adult_content"] is False
    assert raw["_agent_context_signal"]["topic_shift"] is True
    assert raw["_agent_context_signal"]["inherited"] is False
    assert raw["_agent_context_signal"]["inherit_mode"] == "none"
    assert raw["_agent_context_signal"]["blocked_terms"] == ["bimbo"]
    assert raw["_agent_context_signal"]["skipped_reason"] == "topic_shift"
    assert raw["_agent_context_signal"]["overridden_by_current_signal"] is True
    assert raw["_agent_context_signal"]["inherited_fields"] == []


def test_apply_followup_context_tolerates_invalid_quality_score():
    raw = {"keywords": ["related"], "games": [], "sources": [], "categories": []}
    context = {
        "source": "recent_user",
        "keywords": ["bimbo"],
        "quality_score": "bad",
    }

    apply_followup_context(raw, context, "继续找相关的")

    assert raw["_agent_context_signal"]["quality_score"] == 0.0


def test_apply_followup_context_does_not_copy_adult_topic_into_strong_new_outfit_query():
    raw = {
        "keywords": ["skyrim", "outfit"],
        "games": ["Skyrim"],
        "sources": [],
        "categories": ["Outfit"],
        "adult_content": None,
    }
    context = {
        "source": "recent_user",
        "keywords": ["bimbo", "pregnancy"],
        "semantic_anchors": ["pregnancy", "roleplay"],
        "game": "Skyrim Special Edition",
        "source_name": "loverslab",
        "adult_content": True,
        "quality_score": 0.9,
    }

    apply_followup_context(raw, context, "换成 Skyrim 的正常服装 mod")

    assert raw["keywords"] == ["skyrim", "outfit"]
    assert raw["games"] == ["Skyrim"]
    assert raw["sources"] == []
    assert raw["adult_content"] is None
    assert raw["_agent_context_signal"]["inherited"] is False
    assert raw["_agent_context_signal"]["overridden_by_current_signal"] is True


def test_llm_selected_context_does_not_pollute_strong_new_topic_keywords():
    raw = {"keywords": ["性别歧视"], "games": [], "sources": [], "categories": []}
    context = {
        "source": "llm_context_selection",
        "llm_should_inherit": True,
        "llm_confidence": 0.92,
        "llm_reason": "previous bimbo query",
        "keywords": ["bimbo"],
        "semantic_anchors": ["roleplay"],
        "game": "Skyrim Special Edition",
        "source_name": "loverslab",
        "quality_score": 0.95,
    }

    apply_followup_context(raw, context, "性别歧视主题的 mod")

    assert raw["keywords"] == ["性别歧视"]
    assert raw["games"] == []
    assert raw["sources"] == []
    assert raw["_agent_context_hint"]["keywords"] == ["bimbo"]
    signal = raw["_agent_context_signal"]
    assert signal["llm_selected"] is True
    assert signal["inherited"] is False
    assert signal["inherit_mode"] == "none"
    assert signal["primary_keywords"] == ["性别歧视"]
    assert signal["fallback_keywords"] == []
    assert signal["blocked_terms"] == ["bimbo"]
    assert signal["keyword_source"] == "current"
    assert signal["overridden_by_current_signal"] is True


def test_weak_followup_uses_context_fallback_keywords_and_constraints():
    raw = {"keywords": [], "games": [], "sources": [], "categories": [], "adult_content": None}
    context = {
        "source": "recent_user",
        "keywords": ["bimbo"],
        "game": "Skyrim Special Edition",
        "source_name": "loverslab",
        "adult_content": True,
        "sort_field": "updated_at_remote",
        "sort_order": "desc",
        "quality_score": 0.88,
    }

    apply_followup_context(raw, context, "还有更多吗？")

    assert raw["keywords"] == ["bimbo"]
    assert raw["games"] == ["Skyrim Special Edition"]
    assert raw["sources"] == ["loverslab"]
    assert raw["adult_content"] is True
    assert raw["sort_field"] == "updated_at_remote"
    signal = raw["_agent_context_signal"]
    assert signal["inherit_mode"] == "fallback_keywords"
    assert signal["fallback_keywords"] == ["bimbo"]
    assert signal["keyword_source"] == "fallback_from_context"
    assert signal["blocked_terms"] == []


def test_merge_context_keywords_filters_weak_terms():
    merged = merge_context_keywords(
        current_keywords=["curvy", "body", "mod"],
        context_keywords=["bimbo", "style", "mods"],
    )

    assert merged[:3] == ["bimbo", "curvy", "body"]
    assert "mod" not in merged
    assert "style" not in merged


def test_has_refinement_constraints_detects_filter_slots():
    assert has_refinement_constraints({"sort_field": "updated_at_remote"}) is True
    assert has_refinement_constraints({"keywords": ["bimbo"], "games": []}) is False

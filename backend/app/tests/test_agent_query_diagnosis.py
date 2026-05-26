import pytest

from app.services.agent.planning.query_diagnosis import diagnose_query
from app.services.agent.tools.query_diagnosis_tool import QueryDiagnosisInput, QueryDiagnosisTool


def test_diagnosis_uses_context_for_ambiguous_followup():
    diagnosis = diagnose_query(
        query="继续找类似的",
        query_plan={
            "intent": "search",
            "keywords": ["类似"],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={
            "game": "Stellar Blade",
            "source": "nexusmods",
            "adult_content": True,
            "sort_field": "updated_at_remote",
        },
    )

    assert diagnosis["should_clarify"] is False
    assert diagnosis["confidence"] >= 0.7
    assert diagnosis["known_slots"]["game"] == "Stellar Blade"
    assert diagnosis["known_slots"]["source"] == "nexusmods"
    assert diagnosis["known_slots"]["adult_content"] is True
    assert diagnosis["known_slots"]["sort_field"] == "updated_at_remote"
    assert diagnosis["understanding"]["intent"] == diagnosis["intent"]
    assert diagnosis["understanding"]["slots"]["game"] == "Stellar Blade"
    evidence = diagnosis["understanding"]["evidence"]
    assert all(item.get("fragment_id", "").startswith("u_") for item in evidence)
    assert any(item["field"] == "intent" and item["source"] == "query_plan" for item in evidence)
    assert any(item["field"] == "confidence" and item["source"] == "diagnosis" for item in evidence)
    assert any(item["field"] == "game" and item["source"] in {"short_term_memory", "query_plan"} for item in evidence)
    assert diagnosis["understanding"]["followup"] is True


def test_diagnosis_exposes_query_keywords_as_understanding_slots_without_known_scope():
    diagnosis = diagnose_query(
        query="Skyrim bimbo mod",
        query_plan={
            "intent": "search",
            "keywords": ["bimbo"],
            "evidence_id": "ev_keywords",
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
    )

    assert "keywords" not in diagnosis["known_slots"]
    assert diagnosis["understanding"]["slots"]["keywords"] == ["bimbo"]
    evidence = diagnosis["understanding"]["evidence"]
    assert all(item.get("evidence_id") == "ev_keywords" for item in evidence)
    assert any(
        item["field"] == "keywords"
        and item["source"] == "query_plan"
        and item["value"] == ["bimbo"]
        for item in evidence
    )


def test_diagnosis_exposes_query_planning_source_as_evidence():
    diagnosis = diagnose_query(
        query="Skyrim bimbo mod",
        query_plan={
            "intent": "search",
            "keywords": ["bimbo"],
            "_agent_planning_source": "llm",
            "evidence_id": "ev_planning_source",
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
    )

    evidence = diagnosis["understanding"]["evidence"]
    planning_source = [item for item in evidence if item["field"] == "planning_source"]
    llm_used = [item for item in evidence if item["field"] == "llm_planning_used"]
    assert planning_source
    assert planning_source[0]["source"] == "query_plan"
    assert planning_source[0]["value"] == "llm"
    assert llm_used
    assert llm_used[0]["source"] == "query_plan"
    assert llm_used[0]["value"] is True
    assert all(item.get("evidence_id") == "ev_planning_source" for item in evidence)


def test_diagnosis_prefers_llm_semantic_signals_from_query_plan():
    diagnosis = diagnose_query(
        query="这个短语本地语义表不认识",
        query_plan={
            "intent": "search",
            "keywords": [],
            "_agent_planning_source": "llm",
            "_agent_semantic_anchors": ["custom_llm_anchor"],
            "_agent_semantic_domains": ["custom_llm_domain"],
            "_agent_semantic_source": "llm",
            "evidence_id": "ev_llm_semantic",
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
    )

    evidence = diagnosis["understanding"]["evidence"]
    anchor_items = [item for item in evidence if item["field"] == "semantic_anchors"]
    domain_items = [item for item in evidence if item["field"] == "semantic_domains"]
    assert anchor_items
    assert anchor_items[0]["source"] == "llm_query_plan"
    assert anchor_items[0]["value"] == ["custom_llm_anchor"]
    assert domain_items
    assert domain_items[0]["source"] == "llm_query_plan"
    assert domain_items[0]["value"] == ["custom_llm_domain"]
    assert all(item.get("evidence_id") == "ev_llm_semantic" for item in evidence)


def test_diagnosis_derives_domains_for_llm_semantic_anchors_when_missing():
    diagnosis = diagnose_query(
        query="有什么mod支持怀孕玩法",
        query_plan={
            "intent": "search",
            "keywords": [],
            "_agent_planning_source": "llm",
            "_agent_semantic_anchors": ["pregnancy"],
            "_agent_semantic_source": "llm",
            "evidence_id": "ev_llm_semantic_domain",
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
    )

    evidence = diagnosis["understanding"]["evidence"]
    domain_items = [item for item in evidence if item["field"] == "semantic_domains"]
    assert domain_items
    assert domain_items[0]["source"] == "llm_query_plan"
    assert "mechanics" in domain_items[0]["value"]


def test_diagnosis_exposes_llm_planning_error_as_evidence():
    diagnosis = diagnose_query(
        query="有什么mod支持怀孕玩法",
        query_plan={
            "intent": "search",
            "keywords": ["pregnancy"],
            "_agent_planning_source": "fallback",
            "_agent_llm_planning_error_type": "RuntimeError",
            "evidence_id": "ev_planning_error",
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
    )

    evidence = diagnosis["understanding"]["evidence"]
    error_items = [item for item in evidence if item["field"] == "llm_planning_error_type"]
    assert error_items
    assert error_items[0]["source"] == "query_plan"
    assert error_items[0]["value"] == "RuntimeError"
    assert all(item.get("evidence_id") == "ev_planning_error" for item in evidence)


def test_diagnosis_links_all_semantic_signal_logs_to_evidence_id(caplog):
    with caplog.at_level("INFO"):
        diagnose_query(
            query="Skyrim bimbo mod",
            query_plan={
                "intent": "search",
                "keywords": ["bimbo"],
                "evidence_id": "ev_diag_signal",
                "games": [],
                "sources": [],
                "categories": [],
                "adult_content": None,
                "sort_field": "relevance",
                "sort_order": "desc",
            },
            active_constraints={},
        )

    signal_logs = [
        record.message
        for record in caplog.records
        if "agent.tool name=semantic_signal_extractor status=succeeded" in record.message
    ]
    assert signal_logs
    assert all("evidence_id=ev_diag_signal" in message for message in signal_logs)


def test_diagnosis_asks_for_game_when_context_cannot_fill_search_scope():
    diagnosis = diagnose_query(
        query="找成人服装 Mod",
        query_plan={
            "intent": "search",
            "keywords": ["服装"],
            "games": [],
            "sources": [],
            "categories": ["outfit"],
            "adult_content": True,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
    )

    assert diagnosis["should_clarify"] is True
    assert diagnosis["missing_slots"] == ["game"]
    assert "哪个游戏" in diagnosis["clarifying_question"]


def test_diagnosis_current_plan_overrides_context_adult_content():
    diagnosis = diagnose_query(
        query="这次只看非成人内容",
        query_plan={
            "intent": "search",
            "keywords": [],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": False,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={"game": "Stellar Blade", "adult_content": True},
    )

    assert diagnosis["known_slots"]["game"] == "Stellar Blade"
    assert diagnosis["known_slots"]["adult_content"] is False
    assert diagnosis["should_clarify"] is False


def test_diagnosis_uses_favorite_preferences_as_lowest_priority_context():
    diagnosis = diagnose_query(
        query="找最近更新的服装 Mod",
        query_plan={
            "intent": "recent",
            "keywords": ["服装"],
            "games": [],
            "sources": [],
            "categories": ["Outfits"],
            "adult_content": None,
            "sort_field": "updated_at_remote",
            "sort_order": "desc",
        },
        active_constraints={},
        preferences={
            "favorite_summary": {
                "top_games": ["Stellar Blade"],
                "top_sources": ["nexusmods"],
                "adult_content_allowed": True,
            }
        },
    )

    assert diagnosis["should_clarify"] is False
    assert diagnosis["known_slots"]["game"] == "Stellar Blade"
    assert diagnosis["known_slots"]["source"] == "nexusmods"
    assert diagnosis["known_slots"]["adult_content_allowed"] is True
    assert any(
        item["field"] == "source" and item["source"] == "long_term_favorite"
        for item in diagnosis["understanding"]["evidence"]
    )


def test_diagnosis_promotes_install_risk_intent_from_natural_question():
    diagnosis = diagnose_query(
        query="这个 Mod 安装风险高吗，会不会有前置依赖冲突？",
        query_plan={
            "intent": "search",
            "keywords": [],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
    )

    assert diagnosis["intent"] == "install_risk"
    assert diagnosis["should_clarify"] is False


def test_diagnosis_promotes_alternative_intent_and_uses_context():
    diagnosis = diagnose_query(
        query="有没有更稳的替代品？",
        query_plan={
            "intent": "search",
            "keywords": ["bimbo"],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={"game": "Skyrim Special Edition", "source": "nexusmods"},
    )

    assert diagnosis["intent"] == "alternative"
    assert diagnosis["should_clarify"] is False
    assert diagnosis["known_slots"]["game"] == "Skyrim Special Edition"
    assert diagnosis["known_slots"]["source"] == "nexusmods"


def test_diagnosis_promotes_comparison_intent_before_risk_terms():
    diagnosis = diagnose_query(
        query="这两个哪个更适合新手，风险更低？",
        query_plan={
            "intent": "search",
            "keywords": ["Bimbo Body Morph", "Stable Bimbo Preset"],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={"game": "Skyrim Special Edition"},
    )

    assert diagnosis["intent"] == "comparison"
    assert diagnosis["should_clarify"] is False
    assert diagnosis["known_slots"]["game"] == "Skyrim Special Edition"


def test_diagnosis_includes_context_continuity_evidence_when_context_keywords_exist():
    diagnosis = diagnose_query(
        query="继续找 bimbo 同类",
        query_plan={
            "intent": "search",
            "keywords": ["bimbo"],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
        context_keywords=["bimbo", "body"],
    )

    continuity_items = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "context_continuity_score"]
    inherit_items = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "context_inherit_score"]
    topic_shift_items = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "topic_shift_detected"]
    context_source_items = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "context_source"]
    context_quality_items = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "context_quality_score"]
    assert continuity_items
    assert inherit_items
    assert topic_shift_items
    assert context_source_items
    assert context_quality_items
    assert continuity_items[0]["source"] == "short_term_memory"
    assert inherit_items[0]["source"] == "short_term_memory"
    assert topic_shift_items[0]["source"] == "diagnosis"
    assert context_source_items[0]["source"] == "short_term_memory"
    assert context_source_items[0]["value"] == "unknown"
    assert float(context_quality_items[0]["value"]) == 0.0
    assert float(continuity_items[0]["value"]) > 0.5
    assert float(inherit_items[0]["value"]) > 0.4
    assert topic_shift_items[0]["value"] is False


def test_diagnosis_marks_topic_shift_for_new_topic_against_context():
    diagnosis = diagnose_query(
        query="有什么 cyberpunk 2077 载具改装 mod",
        query_plan={
            "intent": "search",
            "keywords": ["cyberpunk", "vehicle"],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
        context_keywords=["bimbo", "body"],
    )

    topic_shift_items = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "topic_shift_detected"]
    assert topic_shift_items
    assert topic_shift_items[0]["value"] is True


def test_diagnosis_marks_topic_shift_when_current_game_conflicts_with_context_game():
    diagnosis = diagnose_query(
        query="cyberpunk vehicle overhaul mod",
        query_plan={
            "intent": "search",
            "keywords": ["vehicle", "overhaul"],
            "games": ["Cyberpunk 2077"],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
        context_keywords=["vehicle", "overhaul"],
        context_slots={"game": "Skyrim Special Edition"},
    )

    topic_shift_items = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "topic_shift_detected"]
    assert topic_shift_items
    assert topic_shift_items[0]["value"] is True


def test_diagnosis_includes_context_inherit_decision_evidence_when_signal_provided():
    diagnosis = diagnose_query(
        query="继续找类似的",
        query_plan={
            "intent": "search",
            "keywords": ["similar"],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
        context_keywords=["bimbo", "body"],
        context_slots={
            "source": "recent_user",
            "quality_score": 0.54,
            "_agent_context_signal": {
                "inherited": True,
                "inherited_fields": ["keywords", "game"],
                "skipped_reason": "",
                "overridden_by_current_signal": False,
                "inherit_threshold": 0.44,
                "followup_score": 0.72,
                "policy_reasons": ["semantic_anchor_bias"],
            },
        },
    )

    evidence = diagnosis["understanding"]["evidence"]
    inherited = [item for item in evidence if item["field"] == "context_inherited"]
    inherited_fields = [item for item in evidence if item["field"] == "context_inherited_fields"]
    skipped_reason = [item for item in evidence if item["field"] == "context_skipped_reason"]
    overridden = [item for item in evidence if item["field"] == "context_overridden_by_current_signal"]
    threshold = [item for item in evidence if item["field"] == "context_inherit_threshold"]
    followup_score = [item for item in evidence if item["field"] == "context_followup_score"]
    policy_reasons = [item for item in evidence if item["field"] == "context_policy_reasons"]
    assert inherited and inherited[0]["value"] is True
    assert inherited_fields and inherited_fields[0]["value"] == ["keywords", "game"]
    assert skipped_reason and skipped_reason[0]["value"] == ""
    assert overridden and overridden[0]["value"] is False
    assert threshold and float(threshold[0]["value"]) == 0.44
    assert followup_score and float(followup_score[0]["value"]) == 0.72
    assert policy_reasons and policy_reasons[0]["value"] == ["semantic_anchor_bias"]


def test_diagnosis_uses_inherited_context_slots_as_known_scope():
    diagnosis = diagnose_query(
        query="继续找相关的",
        query_plan={
            "intent": "search",
            "keywords": ["bimbo"],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
        context_keywords=["bimbo"],
        context_slots={
            "source": "recent_user",
            "quality_score": 0.82,
            "game": "Skyrim Special Edition",
            "_agent_context_signal": {"inherited": True, "topic_shift": False},
        },
    )

    assert diagnosis["should_clarify"] is False
    assert diagnosis["known_slots"]["game"] == "Skyrim Special Edition"
    evidence = diagnosis["understanding"]["evidence"]
    assert any(
        item["field"] == "game"
        and item["source"] == "short_term_memory"
        and item["value"] == "Skyrim Special Edition"
        for item in evidence
    )


def test_diagnosis_preference_memory_gate_blocks_when_current_signal_is_strong():
    diagnosis = diagnose_query(
        query="cyberpunk vehicle handling overhaul mod",
        query_plan={
            "intent": "search",
            "keywords": ["cyberpunk", "vehicle", "handling"],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
        preferences={
            "favorite_summary": {
                "top_games": ["Skyrim Special Edition"],
                "top_sources": ["nexusmods"],
            }
        },
        context_keywords=["bimbo", "body"],
    )

    assert "game" not in diagnosis["known_slots"]
    pref_applied = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "preference_memory_applied"][0]
    pref_reason = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "preference_memory_reason"][0]
    assert pref_applied["value"] is False
    assert pref_reason["value"] == "strong_current_signal"


def test_diagnosis_preference_memory_gate_blocks_when_preference_is_stale():
    diagnosis = diagnose_query(
        query="找最近更新的服装 Mod",
        query_plan={
            "intent": "recent",
            "keywords": ["服装"],
            "games": [],
            "sources": [],
            "categories": ["Outfits"],
            "adult_content": None,
            "sort_field": "updated_at_remote",
            "sort_order": "desc",
        },
        active_constraints={},
        preferences={
            "favorite_summary": {
                "top_games": ["Stellar Blade"],
                "top_sources": ["nexusmods"],
                "adult_content_allowed": True,
            },
            "memory_meta": {"preference_stale": True, "preferences_age_days": 180},
        },
    )

    assert "source" not in diagnosis["known_slots"]
    pref_applied = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "preference_memory_applied"][0]
    pref_stale = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "preference_memory_stale"][0]
    pref_age = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "preference_memory_age_days"][0]
    pref_reason = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "preference_memory_reason"][0]
    assert pref_applied["value"] is False
    assert pref_stale["value"] is True
    assert pref_age["value"] == 180
    assert pref_reason["value"] == "stale_preference_memory"


@pytest.mark.parametrize(
    ("query", "expected_anchor"),
    [
        ("有什么在玩法上可以扮演bimbo的MOD", "roleplay"),
        ("有什么妓女风格的服装MOD", "sexworker_style"),
        ("有什么mod支持怀孕玩法", "pregnancy"),
        ("爱的实验室有什么体系mod", "loverslab"),
        ("找能让角色走 bimbo 路线的系统 mod", "roleplay"),
        ("有什么生育系统玩法 mod", "pregnancy"),
    ],
)
def test_diagnosis_emits_semantic_anchor_evidence_for_business_examples(query, expected_anchor):
    diagnosis = diagnose_query(
        query=query,
        query_plan={
            "intent": "search",
            "keywords": [],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
    )

    evidence = diagnosis["understanding"]["evidence"]
    anchors = [item for item in evidence if item["field"] == "semantic_anchors"]
    assert anchors
    assert expected_anchor in anchors[0]["value"]


def test_diagnosis_uses_context_semantic_anchors_when_context_keywords_missing():
    diagnosis = diagnose_query(
        query="继续找相关的",
        query_plan={
            "intent": "search",
            "keywords": [],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
        context_keywords=[],
        context_slots={"semantic_anchors": ["pregnancy", "gameplay"], "source": "recent_user", "quality_score": 0.4},
    )

    evidence = diagnosis["understanding"]["evidence"]
    semantic_context = [item for item in evidence if item["field"] == "context_semantic_anchors"]
    continuity = [item for item in evidence if item["field"] == "context_continuity_score"]
    inherit = [item for item in evidence if item["field"] == "context_inherit_score"]
    assert semantic_context
    assert semantic_context[0]["value"] == ["pregnancy", "gameplay"]
    assert continuity
    assert inherit


def test_diagnosis_preference_gate_locks_to_context_when_inherit_decision_true():
    diagnosis = diagnose_query(
        query="继续找相关的",
        query_plan={
            "intent": "search",
            "keywords": [],
            "games": [],
            "sources": [],
            "categories": [],
            "adult_content": None,
            "sort_field": "relevance",
            "sort_order": "desc",
        },
        active_constraints={},
        context_keywords=["bimbo"],
        context_slots={"semantic_anchors": ["bimbo"], "source": "recent_user", "quality_score": 0.4},
        preferences={
            "favorite_summary": {
                "top_games": ["Stellar Blade"],
                "top_sources": ["nexusmods"],
            }
        },
    )
    pref_applied = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "preference_memory_applied"][0]
    pref_reason = [item for item in diagnosis["understanding"]["evidence"] if item["field"] == "preference_memory_reason"][0]
    assert pref_applied["value"] is False
    assert pref_reason["value"] == "context_locked"


def test_query_diagnosis_tool_matches_diagnosis_contract():
    query_plan = {
        "intent": "search",
        "keywords": ["bimbo"],
        "games": [],
        "sources": [],
        "categories": [],
        "adult_content": None,
        "sort_field": "relevance",
        "sort_order": "desc",
    }
    direct = diagnose_query(
        query="继续找 bimbo 同类",
        query_plan=query_plan,
        active_constraints={"game": "Skyrim Special Edition"},
        context_keywords=["bimbo", "body"],
    )
    via_tool = QueryDiagnosisTool().run(
        QueryDiagnosisInput(
            query="继续找 bimbo 同类",
            query_plan=query_plan,
            active_constraints={"game": "Skyrim Special Edition"},
            context_keywords=["bimbo", "body"],
        )
    )

    assert via_tool == direct

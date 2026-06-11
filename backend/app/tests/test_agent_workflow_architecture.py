# 中文注释：说明 backend/app/tests/test_agent_workflow_architecture.py 的模块职责，便于后续维护定位。

from pathlib import Path


def test_agent_service_stays_a_runtime_delegate():
    service_path = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "agent"
        / "chat_service.py"
    )
    source = service_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "WebSearchTool",
        "ToolExecutorTool",
        "CandidateRankingTool",
        "ChatAnswerTool",
        "MemoryWritebackTool",
        "query_mods_with_plan",
        "build_response_cards",
        "normalize_query_plan",
    ]

    assert [token for token in forbidden_tokens if token in source] == []
    assert "AgentRuntime" in source


def test_agent_runtime_stays_request_graph_and_finalization_only():
    runtime_path = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "agent"
        / "runtime.py"
    )
    source = runtime_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "WebSearchTool",
        "ToolExecutorTool",
        "CandidateRankingTool",
        "ChatAnswerTool",
        "MemoryWritebackTool",
        "ExecutorQueryTool",
        "TaskUnderstandingTool",
        "LocalDbSearchTool",
        "ResultFusionRankerTool",
        "ResponseCardBuilderTool",
    ]

    assert [token for token in forbidden_tokens if token in source] == []
    assert "ChatRequestGuardTool" in source
    assert "run_agent_graph" in source
    assert "finalize_chat_response" in source


def test_mod_search_graph_stays_a_pure_stage_orchestrator():
    graph_path = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "agent"
        / "workflows"
        / "mod_search_graph.py"
    )
    source = graph_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "TaskUnderstandingTool",
        "TaskUnderstandingInput",
        "ModDetailAnswerTool",
        "ModDetailAnswerInput",
        "ToolExecutorTool",
        "ToolExecutorInput",
        "CandidateRankingTool",
        "CandidateRankingInput",
        "ChatAnswerTool",
        "ChatAnswerInput",
        "MemoryWritebackTool",
        "AgentAnswerService",
        "WebSearchTool",
    ]

    assert [token for token in forbidden_tokens if token in source] == []
    assert "StateGraph" in source
    assert "diagnose_query_stage" in source
    assert "execute_retrieval_stage" in source
    assert "bounded_react_retrieval_stage" in source
    assert "rank_candidates_stage" in source
    assert "self_correction_review_stage" in source
    assert "generate_chat_answer_stage" in source
    assert "generate_detail_answer_stage" in source


def test_query_diagnosis_delegates_context_policy_to_planning_module():
    diagnosis_path = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "agent"
        / "planning"
        / "query_diagnosis.py"
    )
    source = diagnosis_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "context_keyword_inherit_score",
        "decide_context_inheritance",
        "followup_decision",
        "has_distinctive_keywords",
        "semantic_continuity_score",
        "_build_preference_gate",
    ]

    assert [token for token in forbidden_tokens if token in source] == []
    assert "evaluate_context_diagnosis" in source
    assert "decide_preference_memory_gate" in source


def test_context_summarizer_delegates_context_selection_policy():
    summarizer_path = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "agent"
        / "context"
        / "context_summarizer.py"
    )
    source = summarizer_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "followup_decision",
        "semantic_continuity_score",
        "_should_inherit_active_constraints",
        "_context_quality_score",
    ]

    assert [token for token in forbidden_tokens if token in source] == []
    assert "select_history_query_context" in source
    assert "should_inherit_active_constraints" in source


def test_context_query_plan_delegates_result_reference_policy():
    query_plan_path = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "agent"
        / "planning"
        / "context_query_plan.py"
    )
    source = query_plan_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "_apply_result_reference_context",
        "_is_comparison_followup",
        "_is_mod_reference_followup",
        "_is_referenced_alternative_followup",
        "_is_referenced_similarity_followup",
        "_referenced_index",
        "_should_avoid_prior_results",
        "_ALTERNATIVE_MARKERS",
        "_COMPARISON_MARKERS",
    ]

    assert [token for token in forbidden_tokens if token in source] == []
    assert "apply_result_reference_context" in source


def test_context_query_plan_delegates_memory_context_selection_policy():
    query_plan_path = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "agent"
        / "planning"
        / "context_query_plan.py"
    )
    source = query_plan_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "select_effective_last_query_context",
        "diagnosis_context_from_last_query",
        "history_context_for_diagnosis",
        "history_keywords",
        "long_term_writeback",
        "history_backfill",
        "followup_decision",
        "has_distinctive_keywords",
        "referenced_title_keywords",
    ]

    assert [token for token in forbidden_tokens if token in source] == []
    assert "backfill_query_context_for_planning" in source
    assert "has_query_context_signal" in source


def test_context_query_plan_delegates_context_inheritance_application():
    query_plan_path = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "agent"
        / "planning"
        / "context_query_plan.py"
    )
    source = query_plan_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "decide_context_inheritance",
        "merge_context_keywords",
        "has_refinement_constraints",
        "_copy_context_value",
        "_is_weak_keyword",
        "agent.context_inherit",
    ]

    assert [token for token in forbidden_tokens if token in source] == []
    assert "apply_followup_context" in source


def test_context_query_plan_delegates_active_constraints_and_normalization():
    query_plan_path = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "agent"
        / "planning"
        / "context_query_plan.py"
    )
    source = query_plan_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "_apply_active_constraints",
        "load_slot_options",
        "normalize_query_plan",
        "context_game",
        "query_only",
        "_agent_context_signal",
    ]

    assert [token for token in forbidden_tokens if token in source] == []
    assert "apply_active_constraints" in source
    assert "normalize_context_query_plan" in source

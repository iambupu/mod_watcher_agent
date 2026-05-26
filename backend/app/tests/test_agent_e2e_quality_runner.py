from pathlib import Path

import pytest

from app.services.agent.quality import e2e_runner
from app.services.agent.quality.e2e_runner import (
    expect_field_type_summary,
    load_e2e_quality_cases,
    run_e2e_quality_cases,
    supported_expect_fields,
)


def test_e2e_quality_runner_reports_structured_passes():
    path = Path(__file__).resolve().parents[2] / "tests" / "agent_quality_cases" / "e2e.yaml"
    cases = load_e2e_quality_cases(path)
    report = run_e2e_quality_cases(cases)

    assert len(cases) >= 2
    assert report["total"] == len(cases)
    assert report["failed"] == 0
    assert report["passed"] == len(cases)
    assert report["failed_case_ids"] == []
    assert report["analysis"]["suite"] == "agent_chat_e2e_quality"
    assert report["analysis"]["total_cases"] == len(cases)
    assert report["analysis"]["pass_rate"] == 1.0
    assert report["conclusion"]["status"] == "passed"
    assert report["conclusion"]["ready_for_regression_gate"] is True
    assert isinstance(report["evidence"]["case_results"], list)
    assert len(report["evidence"]["case_results"]) == len(cases)
    assert all(item["passed"] is True for item in report["evidence"]["case_results"])
    first_case_checks = {
        check["name"]
        for check in report["evidence"]["case_results"][0]["checks"]
        if isinstance(check, dict)
    }
    assert "audit.evidence.retrieval_decision.semantic_anchors_contains" in first_case_checks
    assert "audit.evidence.semantic_trace.context_anchors_contains" in first_case_checks
    assert "response.audit.analysis_evidence_conclusion_order" in first_case_checks
    assert "response.audit.analysis_non_empty" in first_case_checks
    assert "response.audit.evidence_non_empty" in first_case_checks
    assert "response.audit.conclusion_non_empty" in first_case_checks
    assert "response.cards.analysis_evidence_conclusion_order" in first_case_checks
    assert "response.cards.analysis_non_empty" in first_case_checks
    assert "response.cards.evidence_non_empty" in first_case_checks
    assert "response.cards.conclusion_non_empty" in first_case_checks
    assert "response.evidence_ids.understanding.evidence" in first_case_checks
    assert "log.stage.load_state.evidence_id" in first_case_checks
    assert "log.stage.persist_result.evidence_id" in first_case_checks
    assert "response.evidence_ids.memory_evidence" in first_case_checks
    assert "response.evidence_ids.retrieval_evidence" in first_case_checks
    assert "log.tool.chat_request_guard.evidence_id" in first_case_checks
    assert "log.tool.context_summary.evidence_id" in first_case_checks
    assert "log.tool.memory_context_loader.evidence_id" in first_case_checks
    assert "log.tool.memory_writeback.evidence_id" in first_case_checks
    assert "log.tool.semantic_signal_extractor.evidence_id" in first_case_checks
    assert "log.tool.query_diagnosis.evidence_id" in first_case_checks
    assert "log.tool.tool_planner.evidence_id" in first_case_checks
    assert "log.tool.answer_generation.evidence_id" in first_case_checks
    assert "log.tool.response_card_builder.evidence_id" in first_case_checks
    assert "log.tool.chat_answer.evidence_id" in first_case_checks
    online_case_checks = {
        check["name"]
        for item in report["evidence"]["case_results"]
        if item["id"] == "e2e_online_nexus_success_path"
        for check in item["checks"]
        if isinstance(check, dict)
    }
    assert "audit.evidence.web_search.queried" in online_case_checks
    assert "audit.evidence.web_search.online_result_count" in online_case_checks
    assert "audit.evidence.web_search.tools_contains" in online_case_checks
    llm_planning_case_checks = {
        check["name"]
        for item in report["evidence"]["case_results"]
        if item["id"] == "e2e_llm_planning_source_evidence"
        for check in item["checks"]
        if isinstance(check, dict)
    }
    assert "understanding.planning_source" in llm_planning_case_checks
    assert "understanding.llm_planning_used" in llm_planning_case_checks
    llm_planning_error_case_checks = {
        check["name"]
        for item in report["evidence"]["case_results"]
        if item["id"] == "e2e_llm_planning_error_degrades_with_evidence"
        for check in item["checks"]
        if isinstance(check, dict)
    }
    assert "understanding.planning_source" in llm_planning_error_case_checks
    assert "understanding.llm_planning_used" in llm_planning_error_case_checks
    assert "understanding.llm_planning_error_type" in llm_planning_error_case_checks
    memory_writeback_case_checks = {
        check["name"]
        for item in report["evidence"]["case_results"]
        if item["id"] == "e2e_memory_writeback_two_turn_without_history"
        for check in item["checks"]
        if isinstance(check, dict)
    }
    assert "http.status.turn_1" in memory_writeback_case_checks
    assert "http.status.turn_2" in memory_writeback_case_checks
    assert "understanding.context_source" in memory_writeback_case_checks
    candidate_recovery_case_checks = {
        check["name"]
        for item in report["evidence"]["case_results"]
        if item["id"] == "e2e_topic_shift_to_cyberpunk_vehicle"
        for check in item["checks"]
        if isinstance(check, dict)
    }
    assert "retrieval_evidence.stage_contains" in candidate_recovery_case_checks
    assert "retrieval_evidence.tool_contains" in candidate_recovery_case_checks
    assert "retrieval_evidence.reason_contains" in candidate_recovery_case_checks
    target_case_expected_checks = {
        "e2e_bimbo_roleplay_intent": [
            "audit.evidence.retrieval_decision.semantic_anchors_contains",
            "audit.evidence.retrieval_decision.semantic_domains_contains",
            "audit.evidence.semantic_trace.anchors_contains",
            "audit.evidence.semantic_trace.domains_contains",
        ],
        "e2e_prostitute_style_outfit": [
            "audit.evidence.retrieval_decision.semantic_anchors_contains",
            "audit.evidence.retrieval_decision.semantic_domains_contains",
            "audit.evidence.semantic_trace.anchors_contains",
            "audit.evidence.semantic_trace.domains_contains",
        ],
        "e2e_pregnancy_gameplay": [
            "audit.evidence.retrieval_decision.semantic_anchors_contains",
            "audit.evidence.retrieval_decision.semantic_domains_contains",
            "audit.evidence.semantic_trace.anchors_contains",
            "audit.evidence.semantic_trace.domains_contains",
        ],
        "e2e_loverslab_system_mods": [
            "audit.evidence.retrieval_decision.semantic_anchors_contains",
            "audit.evidence.retrieval_decision.semantic_domains_contains",
            "audit.evidence.semantic_trace.anchors_contains",
            "audit.evidence.semantic_trace.domains_contains",
        ],
    }
    for case_id, expected_checks in target_case_expected_checks.items():
        check_names = {
            check["name"]
            for item in report["evidence"]["case_results"]
            if item["id"] == case_id
            for check in item["checks"]
            if isinstance(check, dict)
        }
        for check_name in expected_checks:
            assert check_name in check_names


def test_e2e_quality_loader_rejects_non_object_cases(tmp_path):
    path = tmp_path / "bad-e2e.yaml"
    path.write_text("- id: ok\n  message: bimbo\n- bad-case\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"indexes: \[1\]"):
        load_e2e_quality_cases(path)


def test_e2e_quality_runner_fails_unknown_expect_fields():
    report = run_e2e_quality_cases(
        [
            {
                "id": "bad_expect_field",
                "message": "bimbo",
                "expect": {"typo_semantic_anchor": "bimbo"},
            }
        ]
    )

    assert report["failed"] == 1
    assert report["failed_case_ids"] == ["bad_expect_field"]
    checks = report["evidence"]["case_results"][0]["checks"]
    assert checks == [
        {
            "name": "case.expect.supported_fields",
            "passed": False,
            "actual": ["typo_semantic_anchor"],
            "expected": supported_expect_fields(),
        }
    ]


def test_e2e_quality_runner_fails_invalid_expect_field_types():
    report = run_e2e_quality_cases(
        [
            {
                "id": "bad_expect_type",
                "message": "bimbo",
                "expect": {
                    "exclude_titles": "Bimbo Body Morph",
                    "understanding_field_contains": ["semantic_anchors", "bimbo"],
                },
            }
        ]
    )

    assert report["failed"] == 1
    assert report["failed_case_ids"] == ["bad_expect_type"]
    checks = report["evidence"]["case_results"][0]["checks"]
    assert len(checks) == 1
    assert checks[0]["name"] == "case.expect.field_types"
    assert checks[0]["passed"] is False
    assert checks[0]["actual"] == {
        "exclude_titles": "string",
        "understanding_field_contains": "list",
    }
    assert checks[0]["expected"] == expect_field_type_summary()
    assert expect_field_type_summary()["exclude_titles"] == "list"
    assert expect_field_type_summary()["understanding_field_contains"] == "object"
    assert expect_field_type_summary()["audit_web_search_equals"] == "object"
    assert expect_field_type_summary()["audit_web_search_contains"] == "object"
    assert expect_field_type_summary()["retrieval_evidence_contains"] == "object"


def test_e2e_quality_runner_records_case_exceptions(monkeypatch):
    def boom(case, *, fast_mode):  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr(e2e_runner, "_run_single_case", boom)

    report = run_e2e_quality_cases([{"id": "exploding_case", "message": "bimbo"}])

    assert report["failed"] == 1
    assert report["failed_case_ids"] == ["exploding_case"]
    assert report["conclusion"]["status"] == "failed"
    assert report["conclusion"]["ready_for_regression_gate"] is False
    assert report["evidence"]["case_results"][0]["checks"] == [
        {
            "name": "case.exception",
            "passed": False,
            "actual": "RuntimeError",
            "expected": "no exception",
        }
    ]

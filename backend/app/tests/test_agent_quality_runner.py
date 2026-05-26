from pathlib import Path

import pytest

from app.services.agent.quality import runner
from app.services.agent.quality.runner import (
    expect_field_type_summary,
    load_quality_cases,
    run_quality_cases,
    supported_expect_fields,
)


def test_quality_runner_loads_yaml_cases_and_reports_passes():
    path = Path(__file__).resolve().parents[2] / "tests" / "agent_quality_cases" / "core.yaml"

    cases = load_quality_cases(path)
    report = run_quality_cases(cases)

    assert len(cases) >= 3
    assert report["total"] == len(cases)
    assert report["failed"] == 0
    assert report["passed"] == len(cases)
    assert report["failed_case_ids"] == []
    assert report["analysis"]["suite"] == "agent_quality_core"
    assert report["analysis"]["total_cases"] == len(cases)
    assert report["analysis"]["pass_rate"] == 1.0
    assert report["conclusion"]["status"] == "passed"
    assert report["conclusion"]["ready_for_regression_gate"] is True
    assert isinstance(report["evidence"]["case_results"], list)
    assert len(report["evidence"]["case_results"]) == len(cases)
    first_case_checks = {
        check["name"]
        for check in report["evidence"]["case_results"][0]["checks"]
        if isinstance(check, dict)
    }
    assert "diagnosis.understanding_shape" in first_case_checks
    assert "diagnosis.understanding_evidence_ids" in first_case_checks
    target_case_ids = {
        "target_bimbo_roleplay_semantics",
        "target_prostitute_outfit_semantics",
        "target_pregnancy_gameplay_semantics",
        "target_loverslab_framework_semantics",
    }
    seen_target_cases = {item["id"] for item in report["evidence"]["case_results"] if item["id"] in target_case_ids}
    assert seen_target_cases == target_case_ids
    for case_id in target_case_ids:
        target_checks = {
            check["name"]
            for item in report["evidence"]["case_results"]
            if item["id"] == case_id
            for check in item["checks"]
            if isinstance(check, dict)
        }
        assert "diagnosis.understanding.semantic_anchors_contains" in target_checks
        assert "diagnosis.understanding.semantic_domains_contains" in target_checks


def test_quality_runner_loader_rejects_non_object_cases(tmp_path):
    path = tmp_path / "bad-core.yaml"
    path.write_text("- id: ok\n  query: bimbo\n- bad-case\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"indexes: \[1\]"):
        load_quality_cases(path)


def test_quality_runner_fails_unknown_expect_fields():
    report = run_quality_cases(
        [
            {
                "id": "bad_expect_field",
                "query": "bimbo",
                "expect": {"typo_required_terms": ["bimbo"]},
            }
        ]
    )

    assert report["failed"] == 1
    assert report["failed_case_ids"] == ["bad_expect_field"]
    assert report["evidence"]["case_results"][0]["checks"] == [
        {
            "name": "case.expect.supported_fields",
            "passed": False,
            "actual": ["typo_required_terms"],
            "expected": supported_expect_fields(),
        }
    ]


def test_quality_runner_fails_invalid_expect_field_types():
    report = run_quality_cases(
        [
            {
                "id": "bad_expect_type",
                "query": "bimbo",
                "expect": {
                    "required_terms": "bimbo",
                    "topic_shift_detected": "false",
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
        "required_terms": "string",
        "topic_shift_detected": "string",
    }
    assert checks[0]["expected"] == expect_field_type_summary()
    assert expect_field_type_summary()["required_terms"] == "list"
    assert expect_field_type_summary()["understanding_field_contains"] == "object"
    assert expect_field_type_summary()["version"] == "string_or_null"


def test_quality_runner_records_case_exceptions(monkeypatch):
    def boom(case):  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "_case_passes", boom)

    report = run_quality_cases([{"id": "exploding_case", "query": "bimbo"}])

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

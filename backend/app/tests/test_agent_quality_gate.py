# 中文注释：说明 backend/app/tests/test_agent_quality_gate.py 的模块职责，便于后续维护定位。

import json
import subprocess
import sys
from pathlib import Path

from app.services.agent.quality.gate import run_agent_quality_gate


def test_agent_quality_gate_reports_combined_regression_status():
    cases_dir = Path(__file__).resolve().parents[2] / "tests" / "agent_quality_cases"

    report = run_agent_quality_gate(cases_dir=cases_dir)

    assert list(report.keys()) == ["analysis", "evidence", "conclusion"]
    assert report["analysis"]["suite"] == "agent_quality_gate"
    assert report["analysis"]["total_cases"] > 0
    assert report["analysis"]["failed_cases"] == 0
    assert report["evidence"]["failed_suites"] == []
    assert report["evidence"]["failed_case_ids"] == {}
    assert "api_chat_e2e" in report["evidence"]["gate_checks"]
    assert "analysis_evidence_conclusion_format" in report["evidence"]["gate_checks"]
    assert "semantic_direction_assertions" in report["evidence"]["gate_checks"]
    assert "answer_semantic_assertions" in report["evidence"]["gate_checks"]
    assert "source_constraint_assertions" in report["evidence"]["gate_checks"]
    assert "context_continuity_multi_turn" in report["evidence"]["gate_checks"]
    assert report["evidence"]["suite_reports"]["core"]["conclusion"]["ready_for_regression_gate"] is True
    assert report["evidence"]["suite_reports"]["e2e"]["conclusion"]["ready_for_regression_gate"] is True
    assert report["conclusion"]["status"] == "passed"
    assert report["conclusion"]["ready_for_regression_gate"] is True


def test_agent_quality_gate_cli_stdout_is_parseable_json():
    backend_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, "scripts/run_agent_quality_gate.py"],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert list(report.keys()) == ["analysis", "evidence", "conclusion"]
    assert report["conclusion"]["ready_for_regression_gate"] is True
    assert "Scheduler started successfully" not in result.stdout

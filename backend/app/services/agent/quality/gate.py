from pathlib import Path
from typing import Any

from app.services.agent.quality.e2e_runner import load_e2e_quality_cases, run_e2e_quality_cases
from app.services.agent.quality.runner import load_quality_cases, run_quality_cases
from app.utils.numeric import safe_nonnegative_int


def run_agent_quality_gate(*, cases_dir: Path | None = None) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[4]
    resolved_cases_dir = cases_dir or root / "tests" / "agent_quality_cases"
    core_report = run_quality_cases(load_quality_cases(resolved_cases_dir / "core.yaml"))
    e2e_report = run_e2e_quality_cases(load_e2e_quality_cases(resolved_cases_dir / "e2e.yaml"))
    reports = {
        "core": core_report,
        "e2e": e2e_report,
    }
    failed_suites = [name for name, report in reports.items() if safe_nonnegative_int(report.get("failed")) > 0]
    failed_case_ids = {
        name: report.get("failed_case_ids") or []
        for name, report in reports.items()
        if report.get("failed_case_ids")
    }
    total_cases = sum(safe_nonnegative_int(report.get("total")) for report in reports.values())
    failed_cases = sum(safe_nonnegative_int(report.get("failed")) for report in reports.values())
    passed_cases = total_cases - failed_cases
    return {
        "analysis": {
            "suite": "agent_quality_gate",
            "case_sources": {
                "core": str(resolved_cases_dir / "core.yaml"),
                "e2e": str(resolved_cases_dir / "e2e.yaml"),
            },
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "failed_cases": failed_cases,
            "pass_rate": round((passed_cases / total_cases), 3) if total_cases else 1.0,
        },
        "evidence": {
            "suite_reports": reports,
            "failed_suites": failed_suites,
            "failed_case_ids": failed_case_ids,
            "gate_checks": [
                "core_task_understanding",
                "api_chat_e2e",
                "context_memory_writeback",
                "web_search_evidence",
                "analysis_evidence_conclusion_format",
                "semantic_direction_assertions",
                "answer_semantic_assertions",
                "source_constraint_assertions",
                "context_continuity_multi_turn",
            ],
        },
        "conclusion": {
            "status": "passed" if not failed_suites else "failed",
            "ready_for_regression_gate": not failed_suites,
            "failed_suites": failed_suites,
        },
    }

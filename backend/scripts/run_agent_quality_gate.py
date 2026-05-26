import argparse
import contextlib
import io
import json
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent.quality.gate import run_agent_quality_gate  # noqa: E402


def _run_gate(cases_dir: Path, *, verbose: bool) -> tuple[dict, str]:
    if verbose:
        return run_agent_quality_gate(cases_dir=cases_dir), ""

    captured_logs = io.StringIO()
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    root_logger.setLevel(logging.WARNING)
    try:
        with contextlib.redirect_stderr(captured_logs):
            report = run_agent_quality_gate(cases_dir=cases_dir)
    finally:
        root_logger.setLevel(previous_level)
    return report, captured_logs.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Agent quality gate.")
    parser.add_argument(
        "--cases-dir",
        type=Path,
        default=BACKEND_ROOT / "tests" / "agent_quality_cases",
        help="Directory containing core.yaml and e2e.yaml.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Keep INFO logs visible while the gate runs.",
    )
    args = parser.parse_args()
    report, captured_logs = _run_gate(args.cases_dir, verbose=args.verbose)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    passed = bool(report["conclusion"]["ready_for_regression_gate"])
    if captured_logs and not passed:
        print(captured_logs, file=sys.stderr, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

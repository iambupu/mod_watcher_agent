from __future__ import annotations

import ast
from pathlib import Path


def test_alembic_file_config_preserves_existing_desktop_loggers() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    env_path = backend_root / "alembic" / "env.py"
    tree = ast.parse(env_path.read_text(encoding="utf-8"), filename=str(env_path))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "fileConfig"
    ]

    assert len(calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
    assert ast.literal_eval(keywords["disable_existing_loggers"]) is False

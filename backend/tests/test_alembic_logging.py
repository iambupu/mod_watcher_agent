from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
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

    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    parent = parents[calls[0]]
    while not isinstance(parent, ast.If):
        parent = parents[parent]
    guard = ast.unparse(parent.test)
    assert "config.attributes.get" in guard
    assert "configure_logger" in guard
    assert "True" in guard


def test_embedded_database_migration_keeps_redacted_root_handlers(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    log_dir = tmp_path / "logs"
    database_path = tmp_path / "data" / "mod_watcher.db"
    database_path.parent.mkdir(parents=True)
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "LOG_DIR": str(log_dir),
            "MW_USER_DATA_DIR": str(tmp_path),
            "MW_ENV_FILE": str(tmp_path / ".env"),
        }
    )
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, logging; "
                "from app.logger import setup_logging; "
                "setup_logging(); "
                "root=logging.getLogger(); "
                "before=[type(h).__name__ for h in root.handlers]; "
                "from app import db; db.init_db(); "
                "after=[type(h).__name__ for h in root.handlers]; "
                "logging.getLogger('probe').error('token=after-init-secret'); "
                "[h.flush() for h in root.handlers]; "
                "print(json.dumps({'before':before,'after':after}))"
            ),
        ],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr
    payload = json.loads(probe.stdout.strip().splitlines()[-1])
    assert payload["after"] == payload["before"]
    assert payload["after"] == [
        "StreamHandler",
        "RotatingFileHandler",
        "RingBufferHandler",
    ]
    file_log = (log_dir / "mod_watcher.log").read_text(encoding="utf-8")
    assert "after-init-secret" not in probe.stderr
    assert "after-init-secret" not in file_log
    assert "token=********" in probe.stderr
    assert "token=********" in file_log

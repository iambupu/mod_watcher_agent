"""Named frontend service process for Mod Watcher Agent."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
LOG_DIR = ROOT_DIR / "log"


def set_windows_title(title: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        pass


def subprocess_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mod Watcher frontend service")
    parser.add_argument("--process-name", default="ModWatcherFrontend")
    args = parser.parse_args()

    os.environ["MOD_WATCHER_PROCESS_NAME"] = "ModWatcherFrontend"
    set_windows_title(args.process_name)
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "frontend_service.log").open("a", encoding="utf-8") as log:
        log.write("\n=== starting frontend service ===\n")
        log.flush()
        proc = subprocess.Popen(
            [npm_cmd, "run", "dev"],
            cwd=str(FRONTEND_DIR),
            env={**os.environ, "MOD_WATCHER_PROCESS_NAME": "ModWatcherFrontendNode"},
            stdout=log,
            stderr=subprocess.STDOUT,
            **subprocess_kwargs(),
        )
        try:
            sys.exit(proc.wait())
        except KeyboardInterrupt:
            proc.terminate()
            sys.exit(130)

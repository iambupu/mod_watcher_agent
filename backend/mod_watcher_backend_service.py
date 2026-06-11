# 中文注释：Windows 服务入口，用于托管后端进程生命周期。

"""Named backend service process for Mod Watcher Agent."""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn


def set_windows_title(title: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mod Watcher backend service")
    parser.add_argument("--process-name", default="ModWatcherBackend")
    args = parser.parse_args()

    os.environ["MOD_WATCHER_PROCESS_NAME"] = "ModWatcherBackend"
    os.environ.setdefault("MW_BIND_HOST", "127.0.0.1")
    set_windows_title(args.process_name)
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=17500,
        log_config=None,
    )

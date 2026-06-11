# 中文注释：封装后端服务层的日志目录定位逻辑。

import os
import platform
import subprocess
from pathlib import Path

from app.logger import get_log_directory


class LogDirectoryOpenError(RuntimeError):
    def __init__(self, message: str, *, unsupported: bool = False) -> None:
        super().__init__(message)
        self.unsupported = unsupported


def open_log_directory_in_system() -> Path:
    log_dir = get_log_directory()
    log_dir.mkdir(parents=True, exist_ok=True)
    system = platform.system().lower()
    try:
        if system == "windows":
            os.startfile(str(log_dir))  # type: ignore[attr-defined]
        elif system == "darwin":
            subprocess.Popen(["open", str(log_dir)])
        elif system == "linux":
            subprocess.Popen(["xdg-open", str(log_dir)])
        else:
            raise LogDirectoryOpenError(f"Unsupported platform: {system}", unsupported=True)
    except FileNotFoundError as exc:
        raise LogDirectoryOpenError(f"Open directory command unavailable: {exc}", unsupported=True) from exc
    return log_dir

import os
import platform
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.logger import get_log_entries

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
def list_logs(
    level: str | None = Query(None, description="Filter by log level (DEBUG, INFO, WARNING, ERROR)"),
    search: str | None = Query(None, description="Search in module name and message"),
    limit: int = Query(200, ge=1, le=1000, description="Maximum entries to return"),
):
    """查询并返回列表数据。"""
    entries = get_log_entries(level=level, search=search, limit=limit)
    return {"entries": entries}


@router.post("/open-dir")
def open_log_directory():
    """处理当前模块的业务逻辑并返回结果。"""
    log_dir = Path(settings.LOG_DIR).resolve()
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
            raise HTTPException(status_code=501, detail=f"Unsupported platform: {system}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=501, detail=f"Open directory command unavailable: {exc}") from exc
    return {"opened": True, "path": str(log_dir)}

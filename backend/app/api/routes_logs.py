from fastapi import APIRouter, HTTPException, Query

from app.logger import get_log_entries
from app.services.log_directory_service import LogDirectoryOpenError, open_log_directory_in_system

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
    try:
        log_dir = open_log_directory_in_system()
    except LogDirectoryOpenError as exc:
        status_code = 501 if exc.unsupported else 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"opened": True, "path": str(log_dir)}

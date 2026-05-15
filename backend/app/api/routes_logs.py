from fastapi import APIRouter, Query

from app.logger import get_log_entries

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
def list_logs(
    level: str | None = Query(None, description="Filter by log level (DEBUG, INFO, WARNING, ERROR)"),
    search: str | None = Query(None, description="Search in module name and message"),
    limit: int = Query(200, ge=1, le=1000, description="Maximum entries to return"),
):
    entries = get_log_entries(level=level, search=search, limit=limit)
    return {"entries": entries}

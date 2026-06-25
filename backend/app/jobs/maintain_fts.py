from sqlalchemy import text
from sqlmodel import Session

from app.jobs.tracked_jobs import run_tracked_job
from app.services.agent.retrievers.sqlite_fts_retriever import (
    DEFAULT_FTS_REPAIR_LIMIT,
    rebuild_mods_fts,
    repair_stale_mods_fts,
)


async def run_sqlite_fts_incremental_repair(limit: int = DEFAULT_FTS_REPAIR_LIMIT) -> dict:
    async def handler(session: Session) -> dict:
        repaired = repair_stale_mods_fts(session, limit=limit)
        return {
            "items_scanned": limit,
            "items_matched": repaired,
            "repaired": repaired,
            "limit": limit,
        }

    return await run_tracked_job(
        "sqlite_fts_incremental_repair",
        handler,
        metadata={"limit": limit},
    )


async def run_sqlite_fts_full_rebuild() -> dict:
    async def handler(session: Session) -> dict:
        rebuilt = rebuild_mods_fts(session)
        indexed_rows = _indexed_row_count(session) if rebuilt else 0
        return {
            "items_scanned": indexed_rows,
            "items_matched": indexed_rows,
            "rebuilt": rebuilt,
            "indexed_rows": indexed_rows,
        }

    return await run_tracked_job("sqlite_fts_full_rebuild", handler)


def _indexed_row_count(session: Session) -> int:
    return int(session.execute(text("SELECT COUNT(1) FROM mods_fts")).scalar_one() or 0)

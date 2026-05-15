"""Job: Generate AI summaries for newly discovered mods.

Triggers: After discovery jobs complete, or on schedule.
"""
import logging

from sqlmodel import Session

from app.db import engine
from app.jobs.tracked_jobs import run_tracked_job
from app.services.summary_service import SUMMARY_GENERATION_LOCK, SummaryService

logger = logging.getLogger(__name__)


async def generate_summaries(record_job: bool = True) -> dict:
    """Generate summaries for mods that don't have them yet.

    Returns:
        A dict with the count of summaries generated.
    """
    if SUMMARY_GENERATION_LOCK.locked():
        logger.info("Summary generation already running; skipping duplicate request")
        return {"generated": 0, "skipped": True}

    async with SUMMARY_GENERATION_LOCK:
        async def handler(session: Session) -> dict:
            service = SummaryService(session)
            count = await service.generate_missing_summaries()
            logger.info("Generated %s missing summaries", count)
            return {
                "generated": count,
                "skipped": False,
                "items_scanned": count,
                "items_matched": count,
            }

        if record_job:
            return await run_tracked_job("llm_generate_summaries", handler)
        with Session(engine) as session:
            return await handler(session)

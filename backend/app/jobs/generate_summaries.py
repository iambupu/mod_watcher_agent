"""Job: Generate AI summaries for newly discovered mods.

Triggers: After discovery jobs complete, or on schedule.
"""
import logging
import json

from sqlmodel import Session

from app.db import engine
from app.jobs.tracked_jobs import run_tracked_job
from app.services.summary_service import SUMMARY_GENERATION_LOCK, SummaryService
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


def _primary_llm_for_display(session: Session) -> tuple[str, str]:
    settings = SettingsService(session)
    raw = settings.get("llm_providers_json") or "[]"
    try:
        providers = json.loads(raw)
    except json.JSONDecodeError:
        providers = []
    enabled = [
        p for p in providers
        if isinstance(p, dict) and p.get("enabled")
    ]
    enabled.sort(key=lambda p: int(p.get("priority") or 999))
    if enabled:
        provider = str(enabled[0].get("provider") or "openai")
        model = str(enabled[0].get("model") or "")
        return provider, model
    return (
        settings.get("llm_provider") or "openai",
        settings.get("llm_model") or "",
    )


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
            provider, model = _primary_llm_for_display(session)
            logger.info("Generated %s missing summaries", count)
            return {
                "generated": count,
                "skipped": False,
                "llm_provider": provider,
                "llm_model": model,
                "items_scanned": count,
                "items_matched": count,
            }

        if record_job:
            return await run_tracked_job("llm_generate_summaries", handler)
        with Session(engine) as session:
            return await handler(session)

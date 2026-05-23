"""Job: Generate AI summaries for newly discovered mods.

Triggers: After discovery jobs complete, or on schedule.
"""
import logging

from sqlmodel import Session

from app.db import engine
from app.jobs.tracked_jobs import run_tracked_job
from app.services.llm_provider_config import get_provider_chain, resolve_provider_config
from app.services.settings_service import SettingsService
from app.services.summary_service import SUMMARY_GENERATION_LOCK, SummaryService

logger = logging.getLogger(__name__)


def _primary_llm_for_display(session: Session) -> tuple[str, str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    settings = SettingsService(session)
    chain = get_provider_chain(settings)
    if chain:
        provider, _, _, model = resolve_provider_config(chain[0])
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
            """处理当前模块的业务逻辑并返回结果。"""
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


async def run_missing_summaries_job(mod_ids: list[int], language: str) -> None:
    """执行任务流程并返回结果。"""
    if SUMMARY_GENERATION_LOCK.locked():
        return
    async with SUMMARY_GENERATION_LOCK:
        async def handler(session: Session) -> dict:
            """处理当前模块的业务逻辑并返回结果。"""
            service = SummaryService(session)
            count = await service.generate_missing_summaries(
                mod_ids=mod_ids,
                language=language,
            )
            return {
                "items_scanned": len(mod_ids),
                "items_matched": count,
                "generated": count,
                "language": language,
                "mod_ids": mod_ids,
            }

        await run_tracked_job(
            "llm_translate_summaries",
            handler,
            metadata={"language": language, "mod_ids": mod_ids},
        )


async def run_single_summary_job(
    mod_id: int,
    language: str,
    summary_type: str,
) -> None:
    """执行任务流程并返回结果。"""
    async def handler(session: Session) -> dict:
        """处理当前模块的业务逻辑并返回结果。"""
        service = SummaryService(session)
        result = await service.generate_summary(
            mod_id,
            language=language,
            summary_type=summary_type,
        )
        generated = 1 if result.get("model") not in ("error", "none") else 0
        return {
            "items_scanned": 1,
            "items_matched": generated,
            "mod_id": mod_id,
            "language": language,
            "summary_type": summary_type,
            "model": result.get("model"),
        }

    await run_tracked_job(
        f"llm_{'regenerate_summary' if summary_type == 'brief' else 'generate_introduction'}",
        handler,
        metadata={
            "mod_id": mod_id,
            "language": language,
            "summary_type": summary_type,
        },
    )

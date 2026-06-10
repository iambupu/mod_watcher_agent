"""Job: Generate AI summaries for newly discovered mods.

Triggers: After discovery jobs complete, or on schedule.
"""
import logging

from sqlmodel import Session, select

from app.db import engine
from app.jobs.tracked_jobs import run_tracked_job, safe_job_count
from app.models.job_run import JobRun
from app.services.llm_provider_config import get_provider_chain, resolve_provider_config
from app.services.settings_service import SettingsService
from app.services.summary_service import SUMMARY_BATCH_LOCK, SUMMARY_GENERATION_LOCK, SummaryService

logger = logging.getLogger(__name__)
SUMMARY_BATCH_SIZE = 5
MANUAL_SUMMARY_JOB_NAMES = {"llm_regenerate_summary", "llm_translate_summaries"}


class SummaryGenerationError(RuntimeError):
    def __init__(self, message: str, metadata: dict):
        super().__init__(message)
        self.metadata = metadata


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


def _manual_summary_job_pending(session: Session) -> bool:
    job = session.exec(
        select(JobRun.id)
        .where(
            JobRun.job_name.in_(MANUAL_SUMMARY_JOB_NAMES),
            JobRun.status.in_(["queued", "running"]),
        )
        .limit(1)
    ).first()
    return job is not None


async def generate_summaries(
    record_job: bool = True,
    max_items: int | None = SUMMARY_BATCH_SIZE,
) -> dict:
    """Generate summaries for mods that don't have them yet.

    Returns:
        A dict with the count of summaries generated.
    """
    if SUMMARY_BATCH_LOCK.locked():
        logger.info("Summary generation already running; recording skipped duplicate request")

        async def skipped_handler(session: Session) -> dict:  # noqa: ARG001
            return {
                "generated": 0,
                "skipped": True,
                "skip_reason": "summary_generation_locked",
                "items_scanned": 0,
                "items_matched": 0,
                "failures": [],
            }

        if record_job:
            return await run_tracked_job("llm_generate_summaries", skipped_handler)
        return await skipped_handler(None)  # type: ignore[arg-type]

    async with SUMMARY_BATCH_LOCK:
        async def handler(session: Session) -> dict:
            """处理当前模块的业务逻辑并返回结果。"""
            service = SummaryService(session)
            report = await service.generate_missing_summaries_report(
                max_items=max_items,
                should_stop=lambda: _manual_summary_job_pending(session),
            )
            count = safe_job_count(report.get("generated", 0))
            scanned = safe_job_count(report.get("scanned", 0))
            provider, model = _primary_llm_for_display(session)
            logger.info("Generated %s missing summaries out of %s scanned", count, scanned)
            return {
                "generated": count,
                "skipped": False,
                "llm_provider": provider,
                "llm_model": model,
                "items_scanned": scanned,
                "items_matched": count,
                "batch_limit": max_items,
                "failed": report.get("failed", 0),
                "failures": report.get("failures", []),
                "mod_ids": report.get("mod_ids", []),
            }

        if record_job:
            return await run_tracked_job("llm_generate_summaries", handler)
        with Session(engine) as session:
            return await handler(session)


async def run_missing_summaries_job(mod_ids: list[int], language: str) -> None:
    """执行任务流程并返回结果。"""
    if SUMMARY_BATCH_LOCK.locked():
        async def skipped_handler(session: Session) -> dict:  # noqa: ARG001
            return {
                "items_scanned": 0,
                "items_matched": 0,
                "generated": 0,
                "failed": 0,
                "failures": [],
                "language": language,
                "mod_ids": mod_ids,
                "skipped": True,
                "skip_reason": "summary_generation_locked",
            }

        await run_tracked_job(
            "llm_translate_summaries",
            skipped_handler,
            metadata={"language": language, "mod_ids": mod_ids, "skipped": True},
        )
        return
    async with SUMMARY_BATCH_LOCK:
        async def handler(session: Session) -> dict:
            """处理当前模块的业务逻辑并返回结果。"""
            service = SummaryService(session)
            report = await service.generate_missing_summaries_report(
                mod_ids=mod_ids,
                language=language,
            )
            count = safe_job_count(report.get("generated", 0))
            return {
                "items_scanned": safe_job_count(report.get("scanned", 0)),
                "items_matched": count,
                "generated": count,
                "failed": report.get("failed", 0),
                "failures": report.get("failures", []),
                "language": language,
                "mod_ids": report.get("mod_ids", mod_ids),
                "requested_mod_ids": mod_ids,
                "skipped": False,
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
    async with SUMMARY_GENERATION_LOCK:
        async def handler(session: Session) -> dict:
            """处理当前模块的业务逻辑并返回结果。"""
            return await generate_single_summary_payload(
                session,
                mod_id=mod_id,
                language=language,
                summary_type=summary_type,
            )

        await run_tracked_job(
            f"llm_{'regenerate_summary' if summary_type == 'brief' else 'generate_introduction'}",
            handler,
            metadata={
                "mod_id": mod_id,
                "language": language,
                "summary_type": summary_type,
            },
        )


async def generate_single_summary_payload_locked(
    session: Session,
    *,
    mod_id: int,
    language: str,
    summary_type: str,
) -> dict:
    """Generate one summary while sharing the summary generation concurrency gate."""
    async with SUMMARY_GENERATION_LOCK:
        return await generate_single_summary_payload(
            session,
            mod_id=mod_id,
            language=language,
            summary_type=summary_type,
        )


async def generate_single_summary_payload(
    session: Session,
    *,
    mod_id: int,
    language: str,
    summary_type: str,
) -> dict:
    """Generate one summary and return job metadata payload."""
    service = SummaryService(session)
    result = await service.generate_summary(
        mod_id,
        language=language,
        summary_type=summary_type,
    )
    error = result.get("error")
    generated = 1 if result.get("model") not in ("error", "none") and not error else 0
    if generated <= 0:
        reason = str(error or "summary_not_generated")
        provider = result.get("provider") or "none"
        model = result.get("model") or "none"
        raise SummaryGenerationError(
            f"{reason}; provider={provider}; model={model}",
            {
                "mod_id": mod_id,
                "language": language,
                "summary_type": summary_type,
                "provider": provider,
                "model": model,
                "error": reason,
                "provider_attempts": result.get("provider_attempts") or [],
            },
        )
    return {
        "items_scanned": 1,
        "items_matched": generated,
        "mod_id": mod_id,
        "language": language,
        "summary_type": summary_type,
        "provider": result.get("provider"),
        "model": result.get("model"),
        "error": error,
        "provider_attempts": result.get("provider_attempts") or [],
    }

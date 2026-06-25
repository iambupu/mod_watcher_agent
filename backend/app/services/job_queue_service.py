import logging

from sqlmodel import Session

from app.jobs.check_favorite_updates import check_favorite_updates
from app.jobs.discover_new_mods import discover_new_mods
from app.jobs.generate_summaries import generate_summaries
from app.jobs.import_nexusmods_game import import_nexusmods_game
from app.jobs.manual_jobs import create_job_run, enqueue_job_run
from app.jobs.tracked_jobs import safe_job_count
from app.models.job_run import JobRun
from app.services.system_notification_service import SystemNotificationService
from app.utils.boolean import parse_bool

logger = logging.getLogger(__name__)


def queue_discover_all(session: Session) -> JobRun:
    job = create_job_run(session, "discover_all")
    _create_queue_event(
        session,
        "job_queued",
        "发现任务已加入队列",
        "正在准备抓取新的 Mod",
    )

    async def handler():
        results = await discover_new_mods()
        scanned, matched = _count_numeric_values(results)
        return {"results": results, "items_scanned": scanned, "items_matched": matched}

    enqueue_job_run(job.id, handler)
    return job


def queue_nexusmods_game_import(
    session: Session,
    *,
    game_domain_name: str,
    batch_size: int,
    max_batches: int | None,
) -> JobRun:
    job = create_job_run(
        session,
        "nexusmods_import_game",
        metadata={
            "game_domain_name": game_domain_name,
            "batch_size": batch_size,
            "max_batches": max_batches,
        },
    )
    _create_queue_event(
        session,
        "job_queued",
        "NexusMods 导入任务已加入队列",
        f"正在分批导入 {game_domain_name} 的 Mod 信息",
    )

    async def handler():
        return await import_nexusmods_game(
            game_domain_name,
            batch_size=batch_size,
            max_batches=max_batches,
        )

    enqueue_job_run(job.id, handler)
    return job


def queue_check_favorites(session: Session) -> JobRun:
    job = create_job_run(session, "check_favorites")

    async def handler():
        results = await check_favorite_updates()
        scanned, matched = _count_favorite_check_result(results)
        return {
            "results": results,
            "items_scanned": scanned,
            "items_matched": matched,
        }

    enqueue_job_run(job.id, handler)
    return job


def queue_generate_summaries(session: Session) -> JobRun:
    job = create_job_run(session, "generate_summaries")

    async def handler():
        results = await generate_summaries(record_job=False)
        generated = safe_job_count(results.get("generated", 0))
        scanned = safe_job_count(results.get("items_scanned", generated))
        return {
            "results": results,
            "items_scanned": scanned,
            "items_matched": generated,
        }

    enqueue_job_run(job.id, handler)
    return job


def _create_queue_event(session: Session, event_type: str, title: str, message: str) -> None:
    try:
        SystemNotificationService(session).create_event(event_type, title, message)
    except Exception:
        session.rollback()
        logger.warning("Failed to create queued job notification: %s", title, exc_info=True)


def _count_numeric_values(result: dict) -> tuple[int, int]:
    scanned = len(result)
    matched = sum(safe_job_count(value) for value in result.values())
    return scanned, matched


def _count_favorite_check_result(result: dict) -> tuple[int, int]:
    summary = result.get("summary") if isinstance(result, dict) else None
    if isinstance(summary, dict):
        return safe_job_count(summary.get("scanned", 0)), safe_job_count(summary.get("updated", 0))
    entries = [value for value in result.values() if isinstance(value, dict)]
    return len(entries), sum(1 for value in entries if parse_bool(value.get("update_detected")))

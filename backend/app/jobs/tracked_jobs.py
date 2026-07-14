import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.db import engine
from app.logger import redact_sensitive_text
from app.models.job_run import JobRun
from app.services.system_notification_service import SystemNotificationService
from app.utils.json import json_object
from app.utils.numeric import safe_nonnegative_int

logger = logging.getLogger(__name__)

TrackedJobHandler = Callable[[Session], Awaitable[dict[str, Any]]]
SQLITE_LOCK_RETRY_ATTEMPTS = 4
SQLITE_LOCK_RETRY_DELAY_SECONDS = 0.25


def utc_now() -> str:
    """返回任务记录统一使用的 UTC ISO 时间。"""
    return datetime.now(UTC).isoformat()


def create_job_run_record(
    session: Session,
    job_name: str,
    metadata: dict[str, Any] | None = None,
) -> JobRun:
    """创建 queued 状态的任务运行记录并立即持久化。"""
    def operation() -> JobRun:
        job_run = JobRun(
            job_name=job_name,
            status="queued",
            started_at=utc_now(),
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        )
        session.add(job_run)
        session.commit()
        session.refresh(job_run)
        return job_run

    return _retry_sqlite_database_locked(session, operation, action=f"create job run {job_name}")


def mark_job_running(session: Session, job_run: JobRun) -> None:
    """把任务标记为 running，并刷新 started_at。"""
    def operation() -> None:
        job_run.status = "running"
        job_run.started_at = utc_now()
        session.add(job_run)
        session.commit()

    _retry_sqlite_database_locked(session, operation, action=f"mark job {job_run.job_name} running")


def mark_job_failed(
    session: Session,
    job_run: JobRun,
    exc: Exception,
    metadata: dict[str, Any] | None = None,
) -> str:
    """把任务标记为 failed，脱敏错误信息并生成系统通知。"""
    redacted_error = redact_sensitive_text(str(exc))

    def operation() -> None:
        job_run.status = "failed"
        job_run.finished_at = utc_now()
        job_run.error_message = redacted_error
        if metadata:
            current = _job_metadata_dict(job_run.metadata_json)
            current.update(metadata)
            job_run.metadata_json = json.dumps(current, ensure_ascii=False)
        session.add(job_run)
        SystemNotificationService(session).create_event(
            "job_failed",
            "任务执行失败",
            f"{job_run.job_name}: {redacted_error}",
        )
        session.commit()

    _retry_sqlite_database_locked(session, operation, action=f"mark job {job_run.job_name} failed")
    return redacted_error


def mark_interrupted_jobs_failed(session: Session) -> int:
    """Mark queued/running jobs from a previous process as failed on startup."""
    interrupted = session.exec(
        select(JobRun).where(JobRun.status.in_(["queued", "running"]))
    ).all()
    if not interrupted:
        return 0

    finished_at = utc_now()
    message = "服务重启或进程退出，任务未完成。"

    def operation() -> None:
        for job_run in interrupted:
            job_run.status = "failed"
            job_run.finished_at = finished_at
            job_run.error_message = message
            session.add(job_run)
        session.commit()

    _retry_sqlite_database_locked(session, operation, action="mark interrupted jobs failed")
    return len(interrupted)


def mark_job_succeeded(session: Session, job_run: JobRun, result: dict[str, Any]) -> None:
    """把任务标记为 succeeded，并把计数和附加 metadata 写回记录。"""
    def operation() -> None:
        metadata = dict(result)
        job_run.status = "succeeded"
        job_run.finished_at = utc_now()
        job_run.items_scanned = safe_job_count(metadata.pop("items_scanned", 0))
        job_run.items_matched = safe_job_count(metadata.pop("items_matched", 0))
        current = _job_metadata_dict(job_run.metadata_json)
        current.update(metadata)
        job_run.metadata_json = json.dumps(current, ensure_ascii=False)
        session.add(job_run)
        session.commit()

    _retry_sqlite_database_locked(session, operation, action=f"mark job {job_run.job_name} succeeded")


def safe_job_count(value: Any) -> int:
    return safe_nonnegative_int(value)


def _job_metadata_dict(metadata_json: str | None) -> dict[str, Any]:
    return json_object(metadata_json)


def create_tracked_job(
    session: Session,
    job_name: str,
    metadata: dict[str, Any] | None = None,
) -> JobRun:
    """兼容旧调用名，创建 tracked job 运行记录。"""
    return create_job_run_record(session, job_name, metadata)


def _retry_sqlite_database_locked(
    session: Session,
    operation: Callable[[], Any],
    *,
    action: str,
) -> Any:
    for attempt in range(1, SQLITE_LOCK_RETRY_ATTEMPTS + 1):
        try:
            return operation()
        except OperationalError as exc:
            if not _is_sqlite_database_locked(exc) or attempt >= SQLITE_LOCK_RETRY_ATTEMPTS:
                raise
            session.rollback()
            delay = SQLITE_LOCK_RETRY_DELAY_SECONDS * attempt
            logger.warning(
                "SQLite database locked while trying to %s; retrying in %.2fs (%s/%s)",
                action,
                delay,
                attempt,
                SQLITE_LOCK_RETRY_ATTEMPTS,
            )
            if delay > 0:
                time.sleep(delay)
    raise RuntimeError("unreachable sqlite lock retry state")


def _is_sqlite_database_locked(exc: OperationalError) -> bool:
    return "database is locked" in str(exc.orig).lower()


async def run_tracked_job(
    job_name: str,
    handler: TrackedJobHandler,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run an async task immediately while recording it in job_runs."""
    with Session(engine) as session:
        job_run = create_tracked_job(session, job_name, metadata=metadata)
        mark_job_running(session, job_run)
        job_run_id = int(job_run.id)

    try:
        with Session(engine) as session:
            result = await handler(session)
    except Exception as exc:
        logger.exception("Tracked job %s failed", job_name)
        with Session(engine) as session:
            job_run = session.get(JobRun, job_run_id)
            if job_run is not None:
                mark_job_failed(session, job_run, exc, getattr(exc, "metadata", None))
        raise

    with Session(engine) as session:
        job_run = session.get(JobRun, job_run_id)
        if job_run is not None:
            mark_job_succeeded(session, job_run, result)
    return result

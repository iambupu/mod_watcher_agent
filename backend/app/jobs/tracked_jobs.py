import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.db import engine
from app.logger import redact_sensitive_text
from app.models.job_run import JobRun
from app.services.system_notification_service import SystemNotificationService

logger = logging.getLogger(__name__)

TrackedJobHandler = Callable[[Session], Awaitable[dict[str, Any]]]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def create_tracked_job(
    session: Session,
    job_name: str,
    metadata: dict[str, Any] | None = None,
) -> JobRun:
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


async def run_tracked_job(
    job_name: str,
    handler: TrackedJobHandler,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run an async task immediately while recording it in job_runs."""
    with Session(engine) as session:
        job_run = create_tracked_job(session, job_name, metadata=metadata)
        job_run.status = "running"
        job_run.started_at = utc_now()
        session.add(job_run)
        job_run_id = int(job_run.id)

    try:
        with Session(engine) as session:
            result = await handler(session)
    except Exception as exc:
        logger.exception("Tracked job %s failed", job_name)
        with Session(engine) as session:
            job_run = session.get(JobRun, job_run_id)
            if job_run is not None:
                job_run.status = "failed"
                job_run.finished_at = utc_now()
                redacted_error = redact_sensitive_text(str(exc))
                job_run.error_message = redacted_error
                session.add(job_run)
                SystemNotificationService(session).create_event(
                    "job_failed",
                    "任务执行失败",
                    f"{job_name}: {redacted_error}",
                )
                session.commit()
        raise

    with Session(engine) as session:
        job_run = session.get(JobRun, job_run_id)
        if job_run is not None:
            job_run.status = "succeeded"
            job_run.finished_at = utc_now()
            job_run.items_scanned = int(result.get("items_scanned", 0) or 0)
            job_run.items_matched = int(result.get("items_matched", 0) or 0)
            job_run.metadata_json = json.dumps(result, ensure_ascii=False)
            session.add(job_run)
            session.commit()
    return result

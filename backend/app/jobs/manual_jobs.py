import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from apscheduler.triggers.date import DateTrigger
from sqlmodel import Session

from app.db import engine
from app.jobs.scheduler import scheduler
from app.models.job_run import JobRun
from app.services.system_notification_service import SystemNotificationService

logger = logging.getLogger(__name__)

JobHandler = Callable[[], Awaitable[dict[str, Any]]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job_run(
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


def enqueue_job_run(job_run_id: int, handler: JobHandler) -> None:
    scheduler.add_job(
        run_job,
        DateTrigger(run_date=datetime.now(timezone.utc)),
        id=f"manual_job_{job_run_id}",
        name=f"Manual Job {job_run_id}",
        args=[job_run_id, handler],
        replace_existing=True,
        misfire_grace_time=300,
    )


async def run_job(job_run_id: int, handler: JobHandler) -> None:
    with Session(engine) as session:
        job_run = session.get(JobRun, job_run_id)
        if job_run is None:
            logger.warning("Manual job %s no longer exists", job_run_id)
            return
        job_run.status = "running"
        job_run.started_at = utc_now()
        session.add(job_run)
        SystemNotificationService(session).create_event(
            "job_running",
            "任务开始执行",
            f"{job_run.job_name} 正在执行",
        )
        session.commit()

    try:
        result = await handler()
    except Exception as exc:
        logger.exception("Manual job %s failed", job_run_id)
        with Session(engine) as session:
            job_run = session.get(JobRun, job_run_id)
            if job_run is None:
                return
            job_run.status = "failed"
            job_run.finished_at = utc_now()
            job_run.error_message = str(exc)
            session.add(job_run)
            SystemNotificationService(session).create_event(
                "job_failed",
                "任务执行失败",
                f"{job_run.job_name}: {exc}",
            )
            session.commit()
        return

    with Session(engine) as session:
        job_run = session.get(JobRun, job_run_id)
        if job_run is None:
            return
        job_run.status = "succeeded"
        job_run.finished_at = utc_now()
        job_run.items_scanned = int(result.pop("items_scanned", 0) or 0)
        job_run.items_matched = int(result.pop("items_matched", 0) or 0)
        job_run.metadata_json = json.dumps(result, ensure_ascii=False)
        session.add(job_run)
        SystemNotificationService(session).create_event(
            "job_succeeded",
            "任务执行完成",
            f"{job_run.job_name} 已完成，匹配 {job_run.items_matched} 项",
        )
        session.commit()

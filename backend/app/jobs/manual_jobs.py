import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from apscheduler.triggers.date import DateTrigger
from sqlmodel import Session

from app.db import engine
from app.jobs.scheduler import scheduler
from app.jobs.tracked_jobs import (
    create_job_run_record,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
)
from app.models.job_run import JobRun

logger = logging.getLogger(__name__)

JobHandler = Callable[[], Awaitable[dict[str, Any]]]


def create_job_run(
    session: Session,
    job_name: str,
    metadata: dict[str, Any] | None = None,
) -> JobRun:
    """创建并持久化对应的数据。"""
    return create_job_run_record(session, job_name, metadata)


def enqueue_job_run(job_run_id: int, handler: JobHandler) -> None:
    """处理当前模块的业务逻辑并返回结果。"""
    scheduler.add_job(
        run_job,
        DateTrigger(run_date=datetime.now(UTC)),
        id=f"manual_job_{job_run_id}",
        name=f"Manual Job {job_run_id}",
        args=[job_run_id, handler],
        replace_existing=True,
        misfire_grace_time=300,
    )


async def run_job(job_run_id: int, handler: JobHandler) -> None:
    """执行任务流程并返回结果。"""
    with Session(engine) as session:
        job_run = session.get(JobRun, job_run_id)
        if job_run is None:
            logger.warning("Manual job %s no longer exists", job_run_id)
            return
        mark_job_running(session, job_run)

    try:
        result = await handler()
    except Exception as exc:
        logger.exception("Manual job %s failed", job_run_id)
        with Session(engine) as session:
            job_run = session.get(JobRun, job_run_id)
            if job_run is None:
                return
            mark_job_failed(session, job_run, exc, getattr(exc, "metadata", None))
        return

    with Session(engine) as session:
        job_run = session.get(JobRun, job_run_id)
        if job_run is None:
            return
        mark_job_succeeded(session, job_run, result)

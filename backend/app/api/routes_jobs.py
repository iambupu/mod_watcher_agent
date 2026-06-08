from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.base import STATE_RUNNING
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select

from app.db import get_session
from app.jobs.generate_summaries import generate_summaries
from app.jobs.generate_summary_report import generate_summary_report
from app.jobs.scheduler import scheduler
from app.models.favorite import Favorite
from app.models.job_run import JobRun
from app.models.mod import Mod
from app.models.notification import Notification
from app.models.update_event import ModUpdateEvent
from app.models.watch_rule import WatchRule
from app.services.job_queue_service import (
    queue_check_favorites,
    queue_discover_all,
    queue_generate_summaries,
    queue_nexusmods_game_import,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class NexusModsGameImportRequest(BaseModel):
    game_domain_name: str = Field(min_length=1, max_length=255)
    batch_size: int = Field(default=100, ge=1, le=100)
    max_batches: int | None = Field(default=None, ge=1, le=1000)


def _job_to_dict(job: JobRun) -> dict:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return {
        "id": job.id,
        "job_name": job.job_name,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "items_scanned": job.items_scanned,
        "items_matched": job.items_matched,
        "error_message": job.error_message,
        "metadata_json": job.metadata_json,
    }


def _queued_response(job: JobRun) -> dict:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return {"status": "queued", "job_id": job.id}


def _current_week_start_utc_iso() -> str:
    """Return current week start (Monday 00:00 local time) as UTC ISO string."""
    local_now = datetime.now().astimezone()
    week_start_local = local_now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ) - timedelta(days=local_now.weekday())
    return week_start_local.astimezone(UTC).isoformat()


@router.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    """读取并返回对应的数据。"""
    week_start_utc = _current_week_start_utc_iso()
    total_mods = session.exec(select(func.count(Mod.id))).one()
    new_mods_this_week = session.exec(
        select(func.count(Mod.id)).where(Mod.first_seen_at >= week_start_utc)
    ).one()
    total_favorites = session.exec(select(func.count(Favorite.id))).one()
    total_rules = session.exec(select(func.count(WatchRule.id))).one()
    unseen_updates = session.exec(
        select(func.count(ModUpdateEvent.id)).where(ModUpdateEvent.seen.is_(False))
    ).one()
    return {
        "total_mods": total_mods,
        "new_mods_this_week": new_mods_this_week,
        "total_favorites": total_favorites,
        "total_rules": total_rules,
        "unseen_updates": unseen_updates,
    }


@router.get("")
def list_jobs(
    session: Session = Depends(get_session),
):
    """List recent notification records."""
    ns = session.exec(
        select(Notification).order_by(Notification.created_at.desc()).limit(50)
    ).all()
    return [
        {
            "id": n.id,
            "channel": n.channel,
            "subject": n.subject,
            "status": n.status,
            "created_at": n.created_at,
            "sent_at": n.sent_at,
        }
        for n in ns
    ]


@router.get("/status")
def get_scheduler_status():
    """Get the current scheduler status and next run times."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return {
        "running": scheduler.state == STATE_RUNNING,
        "state": scheduler.state,
        "jobs": jobs,
    }


@router.get("/runs/recent")
def list_job_runs(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """List recent manual and scheduled task runs."""
    runs = session.exec(
        select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    ).all()
    return {"items": [_job_to_dict(job) for job in runs]}


@router.get("/{job_id}")
def get_job_run(job_id: int, session: Session = Depends(get_session)):
    """读取并返回对应的数据。"""
    job = session.get(JobRun, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_dict(job)


@router.post("/discover-all", status_code=status.HTTP_202_ACCEPTED)
def discover_all(session: Session = Depends(get_session)):
    """Trigger discovery for all enabled watch rules."""
    job = queue_discover_all(session)
    return _queued_response(job)


@router.post("/nexusmods/import-game", status_code=status.HTTP_202_ACCEPTED)
def import_nexusmods_game_route(
    payload: NexusModsGameImportRequest,
    session: Session = Depends(get_session),
):
    """Queue a batched import of NexusMods metadata for one game domain."""
    game_domain_name = payload.game_domain_name.strip().lower()
    job = queue_nexusmods_game_import(
        session,
        game_domain_name=game_domain_name,
        batch_size=payload.batch_size,
        max_batches=payload.max_batches,
    )
    return _queued_response(job)


@router.post("/check-favorites", status_code=status.HTTP_202_ACCEPTED)
def check_favorites(session: Session = Depends(get_session)):
    """Check all favorited mods for updates."""
    job = queue_check_favorites(session)
    return _queued_response(job)


@router.post("/generate-summaries")
def generate_missing_summaries(background_tasks: BackgroundTasks):
    """Trigger async summary translation using the configured summary language."""
    background_tasks.add_task(generate_summaries)
    return {"status": "queued"}


@router.post("/generate-summaries/run", status_code=status.HTTP_202_ACCEPTED)
def run_generate_missing_summaries(session: Session = Depends(get_session)):
    """Run summary translation immediately and return the result."""
    job = queue_generate_summaries(session)
    return _queued_response(job)


@router.post("/summary-report/run")
async def run_summary_report_now():
    """Run summary report immediately using summary_report_prompt in settings."""
    return await generate_summary_report(force=True)


@router.post("/pause")
def pause_scheduler():
    """Pause the scheduler."""
    scheduler.pause()
    return {"running": scheduler.state == STATE_RUNNING, "state": scheduler.state}


@router.post("/resume")
def resume_scheduler():
    """Resume the scheduler."""
    scheduler.resume()
    return {"running": scheduler.state == STATE_RUNNING, "state": scheduler.state}

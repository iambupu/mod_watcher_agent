from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlmodel import Session, select, func

from app.db import get_session
from app.models.job_run import JobRun
from app.models.notification import Notification
from app.models.mod import Mod
from app.models.favorite import Favorite
from app.models.watch_rule import WatchRule
from app.models.update_event import ModUpdateEvent
from app.jobs.scheduler import scheduler
from app.jobs.discover_new_mods import discover_new_mods
from app.jobs.check_favorite_updates import check_favorite_updates
from app.jobs.generate_summaries import generate_summaries
from app.jobs.manual_jobs import create_job_run, enqueue_job_run

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _job_to_dict(job: JobRun) -> dict:
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
    return {"status": "queued", "job_id": job.id}


def _count_numeric_values(result: dict) -> tuple[int, int]:
    scanned = len(result)
    matched = sum(value for value in result.values() if isinstance(value, int))
    return scanned, matched


@router.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    total_mods = session.exec(select(func.count(Mod.id))).one()
    new_mods_this_week = session.exec(
        select(func.count(Mod.id)).where(Mod.first_seen_at >= week_ago)
    ).one()
    total_favorites = session.exec(select(func.count(Favorite.id))).one()
    total_rules = session.exec(select(func.count(WatchRule.id))).one()
    unseen_updates = session.exec(
        select(func.count(ModUpdateEvent.id)).where(ModUpdateEvent.seen == False)
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
    return {"running": scheduler.running, "jobs": jobs}


@router.get("/runs/recent")
def list_job_runs(
    limit: int = 50,
    session: Session = Depends(get_session),
):
    """List recent manual and scheduled task runs."""
    runs = session.exec(
        select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    ).all()
    return {"items": [_job_to_dict(job) for job in runs]}


@router.get("/{job_id}")
def get_job_run(job_id: int, session: Session = Depends(get_session)):
    job = session.get(JobRun, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_dict(job)


@router.post("/discover-all", status_code=status.HTTP_202_ACCEPTED)
async def discover_all(session: Session = Depends(get_session)):
    """Trigger discovery for all enabled watch rules."""
    job = create_job_run(session, "discover_all")
    from app.services.system_notification_service import SystemNotificationService
    SystemNotificationService(session).create_event(
        "job_queued",
        "发现任务已加入队列",
        "正在准备抓取新的 Mod",
    )

    async def handler():
        results = await discover_new_mods()
        scanned, matched = _count_numeric_values(results)
        return {"results": results, "items_scanned": scanned, "items_matched": matched}

    enqueue_job_run(job.id, handler)
    return _queued_response(job)


@router.post("/check-favorites", status_code=status.HTTP_202_ACCEPTED)
async def check_favorites(session: Session = Depends(get_session)):
    """Check all favorited mods for updates."""
    job = create_job_run(session, "check_favorites")

    async def handler():
        results = await check_favorite_updates()
        entries = [value for value in results.values() if isinstance(value, dict)]
        matched = sum(1 for value in entries if value.get("update_detected"))
        return {
            "results": results,
            "items_scanned": len(entries),
            "items_matched": matched,
        }

    enqueue_job_run(job.id, handler)
    return _queued_response(job)


@router.post("/generate-summaries")
async def generate_missing_summaries(background_tasks: BackgroundTasks):
    """Trigger async summary translation using the configured summary language."""
    background_tasks.add_task(generate_summaries)
    return {"status": "queued"}


@router.post("/generate-summaries/run", status_code=status.HTTP_202_ACCEPTED)
async def run_generate_missing_summaries(session: Session = Depends(get_session)):
    """Run summary translation immediately and return the result."""
    job = create_job_run(session, "generate_summaries")

    async def handler():
        results = await generate_summaries(record_job=False)
        generated = int(results.get("generated", 0) or 0)
        return {
            "results": results,
            "items_scanned": generated,
            "items_matched": generated,
        }

    enqueue_job_run(job.id, handler)
    return _queued_response(job)


@router.post("/pause")
async def pause_scheduler():
    """Pause the scheduler."""
    scheduler.pause()
    return {"running": False}


@router.post("/resume")
async def resume_scheduler():
    """Resume the scheduler."""
    scheduler.resume()
    return {"running": True}

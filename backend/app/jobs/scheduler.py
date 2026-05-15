from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from app.config import settings
from app.jobs.check_favorite_updates import check_favorite_updates
from app.jobs.generate_summaries import generate_summaries
from app.jobs.generate_summary_report import generate_summary_report
from app.jobs.tracked_jobs import run_tracked_job
from app.jobs.send_digest import send_digest
from app.models.watch_rule import WatchRule
from app.db import engine
from app.services.settings_service import SettingsService
from app.services.discovery_service import DiscoveryService

scheduler = AsyncIOScheduler()


async def _discover_single_rule(rule_id: int, rule_name: str) -> dict:
    async def handler(db_session: Session) -> dict:
        discovery = DiscoveryService(db_session)
        new_mods = await discovery.discover_from_rule(rule_id)
        return {
            "rule_id": rule_id,
            "rule_name": rule_name,
            "new_mods": len(new_mods),
            "items_scanned": 1,
            "items_matched": len(new_mods),
        }

    return await run_tracked_job("run_rule_discovery", handler)


def register_jobs(session: Session | None = None) -> None:
    if session is None:
        with Session(engine) as db_session:
            register_jobs(db_session)
        return

    rule_jobs = set()
    rules = session.exec(select(WatchRule).where(WatchRule.enabled == True)).all()
    for rule in rules:
        if rule.id is None:
            continue
        rule_job_id = f"discover_rule_{rule.id}"
        rule_jobs.add(rule_job_id)
        scheduler.add_job(
            _discover_single_rule,
            IntervalTrigger(minutes=max(1, int(rule.interval_minutes or 360))),
            id=rule_job_id,
            name=f"Discover Rule: {rule.name}",
            args=[rule.id, rule.name],
            replace_existing=True,
        )

    for job in scheduler.get_jobs():
        if job.id.startswith("discover_rule_") and job.id not in rule_jobs:
            scheduler.remove_job(job.id)

    scheduler.add_job(
        check_favorite_updates,
        IntervalTrigger(hours=12),
        id="check_favorite_updates",
        name="Check Favorite Updates",
        replace_existing=True,
    )
    scheduler.add_job(
        generate_summaries,
        IntervalTrigger(minutes=15),
        id="generate_summaries",
        name="Generate AI Summaries",
        replace_existing=True,
    )
    summary_report_interval = 0
    summary_report_prompt = ""
    try:
        svc = SettingsService(session)
        summary_report_interval = int(svc.get("summary_report_interval_minutes") or "0")
        summary_report_prompt = (svc.get("summary_report_prompt") or "").strip()
    except Exception:
        summary_report_interval = 0
        summary_report_prompt = ""

    if summary_report_interval > 0 and summary_report_prompt:
        scheduler.add_job(
            generate_summary_report,
            IntervalTrigger(minutes=summary_report_interval),
            id="llm_summary_report",
            name="LLM Summary Report",
            replace_existing=True,
        )
    else:
        if scheduler.get_job("llm_summary_report"):
            scheduler.remove_job("llm_summary_report")

    scheduler.add_job(
        send_digest,
        CronTrigger.from_crontab(settings.DIGEST_CRON),
        id="send_digest",
        name="Daily Digest",
        replace_existing=True,
    )


async def setup_scheduler(session: Session | None = None) -> None:
    register_jobs(session)
    scheduler.start()

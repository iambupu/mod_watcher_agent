import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

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
from app.models.job_run import JobRun
from app.models.watch_rule import WatchRule
from app.db import engine
from app.services.settings_service import SettingsService
from app.services.discovery_service import DiscoveryService

scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)
_RULE_WATCHDOG_LOCK = asyncio.Lock()


def _safe_int(
    value: str | None,
    default: int,
    min_value: int = 1,
    max_value: int | None = None,
) -> int:
    try:
        parsed = int(value or "")
    except (TypeError, ValueError):
        return default
    if parsed < min_value:
        return default
    if max_value is not None and parsed > max_value:
        return max_value
    return parsed


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

    return await run_tracked_job(
        "run_rule_discovery",
        handler,
        metadata={"rule_id": rule_id, "rule_name": rule_name},
    )


def _parse_iso_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _extract_rule_id(metadata_json: str | None) -> int | None:
    if not metadata_json:
        return None
    try:
        parsed = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    rule_id = parsed.get("rule_id")
    if isinstance(rule_id, int) and rule_id > 0:
        return rule_id
    return None


async def _run_rule_watchdog() -> dict:
    if _RULE_WATCHDOG_LOCK.locked():
        return {"triggered": 0, "skipped_locked": True}

    async with _RULE_WATCHDOG_LOCK:
        with Session(engine) as session:
            settings_svc = SettingsService(session)
            grace_minutes = _safe_int(
                settings_svc.get("watchdog_grace_minutes"),
                default=60,
                min_value=1,
                max_value=1440,
            )
            max_catchup_per_run = _safe_int(
                settings_svc.get("watchdog_max_catchup_per_run"),
                default=3,
                min_value=1,
                max_value=20,
            )
            rules = session.exec(
                select(WatchRule).where(WatchRule.enabled == True)
            ).all()

            recent_runs = session.exec(
                select(JobRun)
                .where(JobRun.job_name == "run_rule_discovery")
                .order_by(JobRun.started_at.desc())
                .limit(2000)
            ).all()

        latest_by_rule: dict[int, datetime] = {}
        running_rule_ids: set[int] = set()
        for run in recent_runs:
            rule_id = _extract_rule_id(run.metadata_json)
            if rule_id is None:
                continue
            last_at = _parse_iso_time(run.finished_at) or _parse_iso_time(run.started_at)
            if last_at is not None and rule_id not in latest_by_rule:
                latest_by_rule[rule_id] = last_at
            if run.status == "running":
                running_rule_ids.add(rule_id)

        now = datetime.now(timezone.utc)
        overdue_rules: list[WatchRule] = []
        for rule in sorted(rules, key=lambda item: int(item.id or 0)):
            if rule.id is None:
                continue
            if rule.id in running_rule_ids:
                continue
            interval_minutes = max(1, int(rule.interval_minutes or 360))
            overdue_limit = timedelta(minutes=interval_minutes + grace_minutes)
            last_at = latest_by_rule.get(rule.id)
            if last_at is None:
                # Rule has no recorded run yet; watchdog should bootstrap it.
                overdue_rules.append(rule)
                continue
            if now - last_at >= overdue_limit:
                overdue_rules.append(rule)

        triggered = 0
        for rule in overdue_rules[:max_catchup_per_run]:
            try:
                await _discover_single_rule(int(rule.id), rule.name)
                triggered += 1
            except Exception:
                logger.exception("Rule watchdog failed to execute rule %s", rule.id)

        return {
            "triggered": triggered,
            "skipped_locked": False,
            "overdue_total": len(overdue_rules),
            "max_catchup_per_run": max_catchup_per_run,
        }


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
    watchdog_interval = 10
    try:
        svc = SettingsService(session)
        watchdog_interval = _safe_int(
            svc.get("watchdog_check_interval_minutes"),
            default=10,
            min_value=1,
            max_value=180,
        )
    except Exception:
        watchdog_interval = 10

    scheduler.add_job(
        _run_rule_watchdog,
        IntervalTrigger(minutes=watchdog_interval),
        id="rule_watchdog",
        name="Rule Watchdog",
        replace_existing=True,
        max_instances=1,
    )


async def setup_scheduler(session: Session | None = None) -> None:
    register_jobs(session)
    scheduler.start()

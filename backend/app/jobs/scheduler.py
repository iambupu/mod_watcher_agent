import asyncio
import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, select

from app.db import engine
from app.jobs.check_favorite_updates import check_favorite_updates
from app.jobs.generate_summaries import SUMMARY_BATCH_SIZE, generate_summaries
from app.jobs.generate_summary_report import generate_summary_report
from app.jobs.refresh_agent_preferences import refresh_agent_preferences
from app.jobs.send_digest import run_digest_catchup, send_daily_digest, send_weekly_digest
from app.jobs.tracked_jobs import run_tracked_job
from app.models.job_run import JobRun
from app.models.watch_rule import WatchRule
from app.services.discovery_service import DiscoveryService
from app.services.rule_service import safe_interval_minutes
from app.services.settings_service import SettingsService
from app.services.summary_report_service import summary_report_interval_minutes
from app.utils.json import json_object
from app.utils.numeric import bounded_int
from app.utils.time import parse_utc_datetime

scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)
_RULE_WATCHDOG_LOCK = asyncio.Lock()
SUMMARY_REPORT_JOB_ID = "llm_summary_report"
SUMMARY_REPORT_CATCHUP_JOB_ID = "llm_summary_report_catchup"


async def _discover_single_rule(rule_id: int, rule_name: str) -> dict:
    """执行单条规则发现，并用 tracked job 记录运行结果。"""

    async def handler(db_session: Session) -> dict:
        """在 tracked job 会话中运行规则发现服务。"""
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


def _extract_rule_id(metadata_json: str | None) -> int | None:
    """从任务 metadata 中提取规则 ID，用于 watchdog 判断最近运行时间。"""
    parsed = json_object(metadata_json)
    if not parsed:
        return None
    rule_id = parsed.get("rule_id")
    if isinstance(rule_id, int) and rule_id > 0:
        return rule_id
    if isinstance(rule_id, str):
        try:
            parsed_rule_id = int(rule_id)
        except ValueError:
            return None
        return parsed_rule_id if parsed_rule_id > 0 else None
    return None


def _should_catch_up_summary_report(
    session: Session,
    interval_minutes: int,
    now: datetime | None = None,
) -> bool:
    """判断摘要报告是否错过了一个调度周期，需要启动补跑。"""
    if interval_minutes <= 0:
        return False

    latest_runs = session.exec(
        select(JobRun)
        .where(JobRun.job_name == SUMMARY_REPORT_JOB_ID)
        .order_by(JobRun.id.desc())
        .limit(20)
    ).all()

    if any(run.status in {"queued", "running"} for run in latest_runs):
        return False

    latest = latest_runs[0] if latest_runs else None
    if latest is None:
        return True

    last_at = parse_utc_datetime(latest.finished_at) or parse_utc_datetime(latest.started_at)
    if last_at is None:
        return True

    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    else:
        current_time = current_time.astimezone(UTC)
    return current_time - last_at >= timedelta(minutes=interval_minutes)


async def _run_rule_watchdog() -> dict:
    """扫描超过规则间隔和宽限期的规则，并限量补跑。"""
    if _RULE_WATCHDOG_LOCK.locked():
        return {"triggered": 0, "skipped_locked": True}

    async with _RULE_WATCHDOG_LOCK:
        with Session(engine) as session:
            settings_svc = SettingsService(session)
            grace_minutes = bounded_int(
                settings_svc.get("watchdog_grace_minutes"),
                default=60,
                minimum=1,
                maximum=1440,
                default_when_below_minimum=True,
            )
            max_catchup_per_run = bounded_int(
                settings_svc.get("watchdog_max_catchup_per_run"),
                default=3,
                minimum=1,
                maximum=20,
                default_when_below_minimum=True,
            )
            rules = session.exec(select(WatchRule).where(WatchRule.enabled.is_(True))).all()

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
            last_at = parse_utc_datetime(run.finished_at) or parse_utc_datetime(run.started_at)
            if last_at is not None and rule_id not in latest_by_rule:
                latest_by_rule[rule_id] = last_at
            if run.status in {"queued", "running"}:
                running_rule_ids.add(rule_id)

        now = datetime.now(UTC)
        overdue_rules: list[WatchRule] = []
        for rule in sorted(rules, key=lambda item: int(item.id or 0)):
            if rule.id is None:
                continue
            if rule.id in running_rule_ids:
                continue
            interval_minutes = safe_interval_minutes(rule.interval_minutes)
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
    """根据当前规则和设置刷新 APScheduler 中的全部定时任务。"""
    if session is None:
        with Session(engine) as db_session:
            register_jobs(db_session)
        return

    rule_jobs = set()
    rules = session.exec(select(WatchRule).where(WatchRule.enabled.is_(True))).all()
    for rule in rules:
        if rule.id is None:
            continue
        rule_job_id = f"discover_rule_{rule.id}"
        rule_jobs.add(rule_job_id)
        scheduler.add_job(
            _discover_single_rule,
            IntervalTrigger(minutes=safe_interval_minutes(rule.interval_minutes)),
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
        IntervalTrigger(minutes=5),
        id="generate_summaries",
        name="Generate AI Summaries",
        kwargs={"max_items": SUMMARY_BATCH_SIZE},
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_agent_preferences,
        IntervalTrigger(minutes=15),
        id="agent_profile_refresh",
        name="Agent Profile Refresh",
        replace_existing=True,
        max_instances=1,
    )
    summary_report_interval = 0
    summary_report_prompt = ""
    try:
        svc = SettingsService(session)
        summary_report_interval = summary_report_interval_minutes(
            svc.get("summary_report_interval_minutes")
        )
        summary_report_prompt = (svc.get("summary_report_prompt") or "").strip()
    except Exception:
        summary_report_interval = 0
        summary_report_prompt = ""

    if summary_report_interval > 0 and summary_report_prompt:
        scheduler.add_job(
            generate_summary_report,
            IntervalTrigger(minutes=summary_report_interval),
            id=SUMMARY_REPORT_JOB_ID,
            name="LLM Summary Report",
            replace_existing=True,
        )
        if _should_catch_up_summary_report(session, summary_report_interval):
            scheduler.add_job(
                generate_summary_report,
                DateTrigger(run_date=datetime.now(UTC) + timedelta(seconds=5)),
                id=SUMMARY_REPORT_CATCHUP_JOB_ID,
                name="LLM Summary Report Catch-up",
                replace_existing=True,
                max_instances=1,
            )
        elif scheduler.get_job(SUMMARY_REPORT_CATCHUP_JOB_ID):
            scheduler.remove_job(SUMMARY_REPORT_CATCHUP_JOB_ID)
    else:
        if scheduler.get_job(SUMMARY_REPORT_JOB_ID):
            scheduler.remove_job(SUMMARY_REPORT_JOB_ID)
        if scheduler.get_job(SUMMARY_REPORT_CATCHUP_JOB_ID):
            scheduler.remove_job(SUMMARY_REPORT_CATCHUP_JOB_ID)

    scheduler.add_job(
        send_daily_digest,
        CronTrigger(hour=8, minute=0),
        id="send_daily_digest",
        name="Daily Digest",
        replace_existing=True,
    )
    scheduler.add_job(
        send_weekly_digest,
        CronTrigger(day_of_week="mon", hour=0, minute=1),
        id="send_weekly_digest",
        name="Weekly Digest",
        replace_existing=True,
    )
    scheduler.add_job(
        run_digest_catchup,
        DateTrigger(run_date=datetime.now(UTC) + timedelta(seconds=5)),
        id="digest_catchup_startup",
        name="Digest Catch-up Startup",
        kwargs={"trigger": "startup"},
        replace_existing=True,
    )
    scheduler.add_job(
        run_digest_catchup,
        IntervalTrigger(hours=1),
        id="digest_catchup",
        name="Digest Catch-up",
        kwargs={"trigger": "hourly"},
        replace_existing=True,
        max_instances=1,
    )
    watchdog_interval = 10
    try:
        svc = SettingsService(session)
        watchdog_interval = bounded_int(
            svc.get("watchdog_check_interval_minutes"),
            default=10,
            minimum=1,
            maximum=180,
            default_when_below_minimum=True,
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
    """注册任务并启动后台调度器。"""
    register_jobs(session)
    scheduler.start()

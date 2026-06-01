from datetime import UTC, datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine, select

from app.jobs.scheduler import (
    _extract_rule_id,
    _run_rule_watchdog,
    _should_catch_up_summary_report,
    register_jobs,
)
from app.models.job_run import JobRun
from app.models.watch_rule import WatchRule
from app.services.settings_service import SettingsService


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _add_summary_run(
    session: Session,
    *,
    status: str = "succeeded",
    started_at: datetime,
    finished_at: datetime | None = None,
) -> None:
    session.add(
        JobRun(
            job_name="llm_summary_report",
            status=status,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat() if finished_at else None,
        )
    )
    session.commit()


class FakeScheduler:
    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, *, id, name, replace_existing=False, **kwargs):
        self.jobs[id] = {
            "func": func,
            "trigger": trigger,
            "name": name,
            "replace_existing": replace_existing,
            **kwargs,
        }

    def get_jobs(self):
        return []

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)


def test_summary_report_catches_up_when_no_previous_run():
    with _session() as session:
        assert _should_catch_up_summary_report(
            session,
            60,
            now=datetime(2026, 5, 22, 20, 50, tzinfo=UTC),
        )


def test_summary_report_catches_up_when_latest_run_is_overdue():
    now = datetime(2026, 5, 22, 20, 50, tzinfo=UTC)
    with _session() as session:
        _add_summary_run(
            session,
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=3) + timedelta(minutes=1),
        )

        assert _should_catch_up_summary_report(session, 60, now=now)


def test_summary_report_does_not_catch_up_when_latest_run_is_recent():
    now = datetime(2026, 5, 22, 20, 50, tzinfo=UTC)
    with _session() as session:
        _add_summary_run(
            session,
            started_at=now - timedelta(minutes=30),
            finished_at=now - timedelta(minutes=29),
        )

        assert not _should_catch_up_summary_report(session, 60, now=now)


def test_summary_report_does_not_catch_up_when_job_is_running():
    now = datetime(2026, 5, 22, 20, 50, tzinfo=UTC)
    with _session() as session:
        _add_summary_run(
            session,
            status="running",
            started_at=now - timedelta(hours=2),
        )

        assert not _should_catch_up_summary_report(session, 60, now=now)


def test_register_jobs_adds_agent_profile_refresh_every_15_minutes(monkeypatch):
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr("app.jobs.scheduler.scheduler", fake_scheduler)

    with _session() as session:
        register_jobs(session)

    job = fake_scheduler.jobs["agent_profile_refresh"]
    assert job["name"] == "Agent Profile Refresh"
    assert job["trigger"].interval.total_seconds() == 15 * 60
    assert job["max_instances"] == 1

    startup_job = fake_scheduler.jobs["digest_catchup_startup"]
    assert startup_job["trigger"].run_date.tzinfo is not None


def test_register_jobs_uses_shared_rule_interval_fallback(monkeypatch):
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr("app.jobs.scheduler.scheduler", fake_scheduler)

    with _session() as session:
        for name, interval_minutes in [("invalid-low-interval-rule", -5), ("invalid-high-interval-rule", 2000)]:
            session.add(
                WatchRule(
                    name=name,
                    enabled=True,
                    source="nexusmods",
                    interval_minutes=interval_minutes,
                    source_config_json="{}",
                    filters_json="{}",
                    notification_json="{}",
                    created_at="2026-05-22T00:00:00+00:00",
                    updated_at="2026-05-22T00:00:00+00:00",
                )
            )
        session.commit()
        rules = session.exec(select(WatchRule)).all()

        register_jobs(session)

    intervals_by_name = {
        rule.name: fake_scheduler.jobs[f"discover_rule_{rule.id}"]["trigger"].interval.total_seconds() / 60
        for rule in rules
    }
    assert intervals_by_name["invalid-low-interval-rule"] == 360
    assert intervals_by_name["invalid-high-interval-rule"] == 1440


def test_register_jobs_recovers_from_bad_summary_report_interval(monkeypatch):
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr("app.jobs.scheduler.scheduler", fake_scheduler)

    with _session() as session:
        settings = SettingsService(session)
        settings.set("summary_report_prompt", "关注热点")
        settings.set("summary_report_interval_minutes", "bad")

        register_jobs(session)

    assert "llm_summary_report" not in fake_scheduler.jobs


def test_extract_rule_id_accepts_numeric_strings():
    assert _extract_rule_id('{"rule_id": "42"}') == 42
    assert _extract_rule_id('{"rule_id": "0"}') is None
    assert _extract_rule_id('{"rule_id": "abc"}') is None
    assert _extract_rule_id("[]") is None


async def _noop_discover(rule_id: int, rule_name: str) -> dict:  # noqa: ARG001
    return {"items_scanned": 1, "items_matched": 0}


def test_rule_watchdog_skips_queued_rule_runs(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            WatchRule(
                name="queued-rule",
                enabled=True,
                source="nexusmods",
                interval_minutes=1,
                source_config_json="{}",
                filters_json="{}",
                notification_json="{}",
                created_at="2026-05-22T00:00:00+00:00",
                updated_at="2026-05-22T00:00:00+00:00",
            )
        )
        session.commit()
        rule = session.exec(select(WatchRule)).one()
        session.add(
            JobRun(
                job_name="run_rule_discovery",
                status="queued",
                started_at="2026-05-22T00:00:00+00:00",
                metadata_json=f'{{"rule_id": {rule.id}}}',
            )
        )
        session.commit()

    monkeypatch.setattr("app.jobs.scheduler.engine", engine)
    calls = []

    async def fake_discover(rule_id: int, rule_name: str):
        calls.append((rule_id, rule_name))
        return await _noop_discover(rule_id, rule_name)

    monkeypatch.setattr("app.jobs.scheduler._discover_single_rule", fake_discover)

    import asyncio

    result = asyncio.run(_run_rule_watchdog())

    assert result["triggered"] == 0
    assert calls == []

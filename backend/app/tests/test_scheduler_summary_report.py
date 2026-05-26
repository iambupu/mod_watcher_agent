from datetime import UTC, datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine

from app.jobs.scheduler import _should_catch_up_summary_report, register_jobs
from app.models.job_run import JobRun


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

    fake_scheduler = FakeScheduler()
    monkeypatch.setattr("app.jobs.scheduler.scheduler", fake_scheduler)

    with _session() as session:
        register_jobs(session)

    job = fake_scheduler.jobs["agent_profile_refresh"]
    assert job["name"] == "Agent Profile Refresh"
    assert job["trigger"].interval.total_seconds() == 15 * 60
    assert job["max_instances"] == 1

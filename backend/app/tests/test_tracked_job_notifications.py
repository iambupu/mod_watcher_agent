import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.jobs.tracked_jobs import run_tracked_job
from app.models.job_run import JobRun


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.mark.asyncio
async def test_tracked_job_notifies_on_failure_only(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    created_events = []

    monkeypatch.setattr("app.jobs.tracked_jobs.engine", engine)
    monkeypatch.setattr(
        "app.jobs.tracked_jobs.SystemNotificationService.create_event",
        lambda self, *args: created_events.append(args),
    )

    async def failing_handler(session: Session):  # noqa: ARG001
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await run_tracked_job("failing_job", failing_handler)

    assert created_events == [
        ("job_failed", "任务执行失败", "failing_job: boom"),
    ]


@pytest.mark.asyncio
async def test_tracked_job_does_not_notify_on_success(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    created_events = []

    monkeypatch.setattr("app.jobs.tracked_jobs.engine", engine)
    monkeypatch.setattr(
        "app.jobs.tracked_jobs.SystemNotificationService.create_event",
        lambda self, *args: created_events.append(args),
    )

    async def success_handler(session: Session):  # noqa: ARG001
        return {"items_scanned": 1, "items_matched": 1}

    result = await run_tracked_job("success_job", success_handler)

    assert result == {"items_scanned": 1, "items_matched": 1}
    assert created_events == []


@pytest.mark.asyncio
async def test_tracked_job_commits_running_status_before_handler(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    observed_statuses = []

    monkeypatch.setattr("app.jobs.tracked_jobs.engine", engine)

    async def observing_handler(session: Session):
        row = session.exec(select(JobRun)).one()
        observed_statuses.append(row.status)
        return {"items_scanned": 0, "items_matched": 0}

    await run_tracked_job("observed_job", observing_handler)

    assert observed_statuses == ["running"]

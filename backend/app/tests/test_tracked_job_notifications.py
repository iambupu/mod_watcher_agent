import json

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.jobs.tracked_jobs import mark_interrupted_jobs_failed, mark_job_succeeded, run_tracked_job
from app.models.job_run import JobRun


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_mark_interrupted_jobs_failed_only_updates_active_statuses():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(JobRun(job_name="queued_job", status="queued", started_at="2026-05-24T00:00:00+00:00"))
        session.add(JobRun(job_name="running_job", status="running", started_at="2026-05-24T00:01:00+00:00"))
        session.add(
            JobRun(
                job_name="done_job",
                status="succeeded",
                started_at="2026-05-24T00:02:00+00:00",
                finished_at="2026-05-24T00:03:00+00:00",
            )
        )
        session.commit()

        assert mark_interrupted_jobs_failed(session) == 2

        rows = {row.job_name: row for row in session.exec(select(JobRun)).all()}
        assert rows["queued_job"].status == "failed"
        assert rows["running_job"].status == "failed"
        assert rows["queued_job"].finished_at is not None
        assert rows["running_job"].error_message == "服务重启或进程退出，任务未完成。"
        assert rows["done_job"].status == "succeeded"


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


def test_mark_job_succeeded_tolerates_invalid_count_fields():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        job = JobRun(job_name="weird_result", status="running", started_at="2026-05-24T00:00:00+00:00")
        session.add(job)
        session.commit()
        session.refresh(job)

        mark_job_succeeded(
            session,
            job,
            {
                "items_scanned": "not-a-number",
                "items_matched": -3,
                "detail": "ok",
            },
        )

        reloaded = session.get(JobRun, job.id)
        assert reloaded.status == "succeeded"
        assert reloaded.items_scanned == 0
        assert reloaded.items_matched == 0
        assert json.loads(reloaded.metadata_json) == {"detail": "ok"}


def test_mark_job_succeeded_preserves_existing_metadata():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        job = JobRun(
            job_name="rule_job",
            status="running",
            started_at="2026-05-24T00:00:00+00:00",
            metadata_json='{"rule_id": 42, "trigger": "manual"}',
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        mark_job_succeeded(
            session,
            job,
            {
                "items_scanned": 2,
                "items_matched": 1,
                "detail": "ok",
            },
        )

        reloaded = session.get(JobRun, job.id)
        assert reloaded.status == "succeeded"
        assert reloaded.items_scanned == 2
        assert reloaded.items_matched == 1
        assert json.loads(reloaded.metadata_json) == {
            "rule_id": 42,
            "trigger": "manual",
            "detail": "ok",
        }


def test_mark_job_succeeded_recovers_from_invalid_existing_metadata():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        job = JobRun(
            job_name="legacy_bad_metadata",
            status="running",
            started_at="2026-05-24T00:00:00+00:00",
            metadata_json="{bad json",
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        mark_job_succeeded(session, job, {"detail": "ok"})

        reloaded = session.get(JobRun, job.id)
        assert reloaded.status == "succeeded"
        assert json.loads(reloaded.metadata_json) == {"detail": "ok"}

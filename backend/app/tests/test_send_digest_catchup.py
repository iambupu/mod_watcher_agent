import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.jobs.send_digest import run_digest_catchup
from app.models.job_run import JobRun


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.mark.asyncio
async def test_digest_catchup_is_recorded_as_tracked_job(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    window = (
        datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
        datetime(2026, 5, 20, 8, 0, tzinfo=UTC),
    )

    monkeypatch.setattr("app.jobs.tracked_jobs.engine", engine)
    monkeypatch.setattr("app.jobs.send_digest._scheduled_window", lambda period: window if period == "daily" else None)

    async def fake_send_for_window(session: Session, period, window_start, window_end, *, force=False):  # noqa: ARG001
        return {
            "generated": True,
            "period": period,
            "items_scanned": 2,
            "items_matched": 2,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        }

    monkeypatch.setattr("app.jobs.send_digest._send_digest_for_window", fake_send_for_window)

    result = await run_digest_catchup(trigger="startup")

    assert result["checked"] is True
    assert result["trigger"] == "startup"
    assert result["items_scanned"] == 2

    with Session(engine) as session:
        rows = session.exec(select(JobRun)).all()

    assert len(rows) == 1
    assert rows[0].job_name == "digest_catchup"
    assert rows[0].status == "succeeded"
    assert rows[0].items_scanned == 2
    metadata = json.loads(rows[0].metadata_json or "{}")
    assert metadata["trigger"] == "startup"
    assert metadata["results"][0]["period"] == "daily"

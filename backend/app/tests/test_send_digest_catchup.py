# 中文注释：说明 backend/app/tests/test_send_digest_catchup.py 的模块职责，便于后续维护定位。

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.jobs.send_digest import _send_digest_for_window, run_digest_catchup
from app.models.job_run import JobRun
from app.models.notification import Notification
from app.models.system_notification import SystemNotificationEvent
from app.services.settings_service import SettingsService


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


@pytest.mark.asyncio
async def test_digest_records_desktop_delivery_when_system_notifications_are_enabled(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    window_start = datetime(2026, 5, 22, 8, 0, tzinfo=UTC)
    window_end = datetime(2026, 5, 23, 8, 0, tzinfo=UTC)

    async def fake_digest_text(settings_svc, period, start, end, mods, updates):  # noqa: ARG001
        return "Digest report", "ollama", "qwen3:8b"

    monkeypatch.setattr("app.jobs.send_digest._generate_digest_text", fake_digest_text)
    monkeypatch.setattr(
        "app.services.system_notification_service.send_windows_notification",
        lambda title, message: True,
    )

    with Session(engine) as session:
        settings = SettingsService(session)
        settings.set("notifications_enabled", "true")
        settings.set("system_notifications_enabled", "true")
        settings.set("telegram_enabled", "false")
        settings.set("discord_enabled", "false")

        result = await _send_digest_for_window(session, "daily", window_start, window_end, force=True)
        notifications = session.exec(select(Notification)).all()
        events = session.exec(select(SystemNotificationEvent)).all()

    assert result["delivery_status"] == "sent"
    assert result["desktop_ok"] is True
    assert result["telegram_ok"] is False
    assert result["discord_ok"] is False
    assert [(row.channel, row.status, row.error_message) for row in notifications] == [
        ("desktop", "sent", None)
    ]
    assert len(events) == 1
    assert events[0].event_type == "daily_digest_complete"
    assert events[0].seen is True

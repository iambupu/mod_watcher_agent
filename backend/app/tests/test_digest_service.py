from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.services.digest_service import send_digest_for_window
from app.services.notification_service import DeliveryResult
from app.services.settings_service import SettingsService


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.mark.asyncio
async def test_send_digest_releases_transaction_before_llm_and_external_notification(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    observed: list[tuple[str, bool]] = []
    window_end = datetime.now(UTC)
    window_start = window_end - timedelta(hours=24)

    async def fake_generate_text(settings_svc, period, start, end, mods, updates):  # noqa: ARG001
        observed.append(("llm", session.in_transaction()))
        return "这是足够长的每日摘要内容，用于发送通知。", "fake", "model"

    async def fake_send_external_channels(self, text):  # noqa: ARG001
        observed.append(("external", self.session.in_transaction()))
        return (
            DeliveryResult(False, "not configured", skipped=True),
            DeliveryResult(False, "not configured", skipped=True),
        )

    async def fake_record(self, channel, recipient, subject, body, status, error_message=None):  # noqa: ARG002
        return None

    monkeypatch.setattr(
        "app.services.digest_service.NotificationService.send_external_channels",
        fake_send_external_channels,
    )
    monkeypatch.setattr(
        "app.services.digest_service.NotificationService._record",
        fake_record,
    )
    monkeypatch.setattr(
        "app.services.digest_service.SystemNotificationService.create_event",
        lambda self, **kwargs: SimpleNamespace(seen=False),
    )

    with Session(engine) as session:
        settings = SettingsService(session)
        settings.set("ui_language", "zh-CN")
        settings.set("notifications_enabled", "false")
        session.add(
            Mod(
                source="nexusmods",
                external_id="digest-transaction",
                game="Skyrim Special Edition",
                title="Digest Mod",
                url="https://example.com/mod/digest-transaction",
                original_summary="A recent digest mod.",
                first_seen_at=(window_end - timedelta(hours=1)).isoformat(),
                last_seen_at=(window_end - timedelta(hours=1)).isoformat(),
            )
        )
        session.commit()

        result = await send_digest_for_window(
            session,
            "daily",
            window_start,
            window_end,
            force=True,
            generate_text=fake_generate_text,
        )

        assert observed == [("llm", False), ("external", False)]
        assert result["generated"] is True

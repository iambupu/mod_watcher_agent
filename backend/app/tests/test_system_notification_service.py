import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.services.settings_service import SettingsService
from app.services.system_notification_service import SystemNotificationService


@pytest.fixture(name="session")
def fixture_session():
    engine = create_engine("sqlite://", echo=False, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_event_dispatches_whitelisted_desktop_notification_and_marks_seen(session, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.services.system_notification_service.send_windows_notification",
        lambda title, message: sent.append((title, message)) or True,
    )

    event = SystemNotificationService(session).create_event(
        "llm_summary_report_complete",
        "摘要汇总报告",
        "摘要汇总报告已完成",
    )

    assert event.seen is True
    assert sent == [("摘要汇总报告", "摘要汇总报告已完成")]


def test_create_event_does_not_dispatch_non_whitelisted_event(session, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.services.system_notification_service.send_windows_notification",
        lambda title, message: sent.append((title, message)) or True,
    )

    event = SystemNotificationService(session).create_event(
        "new_mod_discovered",
        "新 Mod 发现",
        "发现 1 个新 Mod",
    )

    assert event.seen is False
    assert sent == []


def test_create_event_keeps_unseen_when_whitelisted_desktop_dispatch_fails(session, monkeypatch):
    monkeypatch.setattr(
        "app.services.system_notification_service.send_windows_notification",
        lambda title, message: False,
    )

    event = SystemNotificationService(session).create_event(
        "llm_summary_report_complete",
        "摘要汇总报告",
        "摘要汇总报告已完成",
    )

    assert event.seen is False


def test_create_event_respects_system_notification_toggle(session, monkeypatch):
    settings = SettingsService(session)
    settings.set("system_notifications_enabled", "false")
    sent = []
    monkeypatch.setattr(
        "app.services.system_notification_service.send_windows_notification",
        lambda title, message: sent.append((title, message)) or True,
    )

    event = SystemNotificationService(session).create_event(
        "llm_summary_report_complete",
        "摘要汇总报告",
        "摘要汇总报告已完成",
    )

    assert event.seen is False
    assert sent == []

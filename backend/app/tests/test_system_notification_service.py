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


def test_create_event_parses_numeric_system_notification_toggle(session, monkeypatch):
    settings = SettingsService(session)
    settings.set("system_notifications_enabled", "0")
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


def test_mark_seen_counts_only_newly_seen_events(session):
    service = SystemNotificationService(session)
    unseen = service.create_event("custom_event", "失败", "任务失败")
    already_seen = service.create_event("custom_event", "已读", "已读事件")
    already_seen.seen = True
    session.add(already_seen)
    session.commit()

    updated = service.mark_seen([unseen.id, already_seen.id, unseen.id])

    assert updated == 1
    assert session.get(type(unseen), unseen.id).seen is True
    assert session.get(type(already_seen), already_seen.id).seen is True


def test_mark_seen_empty_input_is_noop(session):
    assert SystemNotificationService(session).mark_seen([]) == 0


def test_mark_seen_ignores_bool_and_non_positive_ids(session):
    service = SystemNotificationService(session)
    event = service.create_event("custom_event", "待处理", "待处理事件")

    updated = service.mark_seen([True, 0, -1])

    assert updated == 0
    assert session.get(type(event), event.id).seen is False


def test_get_recent_events_clamps_to_requested_limit(session):
    service = SystemNotificationService(session)
    first = service.create_event("custom_event", "1", "first")
    second = service.create_event("custom_event", "2", "second")

    events = service.get_recent_events(since_id=0, limit=1)

    assert [event.id for event in events] == [second.id]
    assert first.id is not None

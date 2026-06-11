# 中文注释：说明 backend/app/tests/test_notification_service.py 的模块职责，便于后续维护定位。

from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.notification import Notification
from app.services.notification_service import DeliveryResult, NotificationService


@pytest.fixture
def engine():
    e = create_engine("sqlite://", echo=False, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(e)
    return e


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def service(session):
    return NotificationService(session)


@pytest.mark.asyncio
async def test_send_telegram_success(service, monkeypatch):
    monkeypatch.setattr("app.config.settings.TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setattr("app.config.settings.TELEGRAM_CHAT_ID", "fake_chat_id")
    mock_resp = AsyncMock()
    mock_resp.is_success = True
    with patch("httpx.AsyncClient", autospec=True) as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        result = await service.send_telegram_message("test")
        assert result is True


@pytest.mark.asyncio
async def test_send_telegram_no_credentials(service, monkeypatch):
    monkeypatch.setattr("app.config.settings.TELEGRAM_BOT_TOKEN", "")
    result = await service.send_telegram_message("test")
    assert result is False


@pytest.mark.asyncio
async def test_send_telegram_disabled_reports_skipped(service, session):
    from app.services.settings_service import SettingsService

    SettingsService(session).set("telegram_enabled", "false")

    result = await service.send_telegram_message_result("test")

    assert result.ok is False
    assert result.skipped is True
    assert result.reason == "Telegram notification is disabled"


@pytest.mark.asyncio
async def test_send_telegram_parses_numeric_disabled_toggle(service, session):
    from app.services.settings_service import SettingsService

    SettingsService(session).set("telegram_enabled", "0")

    result = await service.send_telegram_message_result("test")

    assert result.ok is False
    assert result.skipped is True
    assert result.reason == "Telegram notification is disabled"


@pytest.mark.asyncio
async def test_send_discord_success(service, monkeypatch):
    monkeypatch.setattr("app.config.settings.DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    mock_resp = AsyncMock()
    mock_resp.is_success = True
    with patch("httpx.AsyncClient", autospec=True) as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        result = await service.send_discord_webhook("test")
        assert result is True


def test_format_update_notification():
    text = NotificationService.format_update_notification("Test Mod", "1.0", "2.0", "https://example.com/mod/1")
    assert "Test Mod" in text
    assert "1.0 \u2192 2.0" in text
    assert "https://example.com/mod/1" in text


def test_format_update_notification_missing_versions():
    text = NotificationService.format_update_notification("Mod X", None, None, "https://x.com")
    assert "? \u2192 ?" in text


def test_format_update_notification_escapes_html():
    text = NotificationService.format_update_notification(
        "Bad <Mod>",
        "1<0",
        "2&0",
        "https://example.com/?q=<script>",
    )

    assert "Bad &lt;Mod&gt;" in text
    assert "1&lt;0 \u2192 2&amp;0" in text
    assert "<script>" not in text


def test_format_daily_digest():
    new_mods = [{"title": "New A", "downloads": 100, "endorsements": 5, "url": "http://a"}]
    updates = [{"mod_title": "Updated B", "old_version": "1.0", "new_version": "1.1"}]
    text = NotificationService.format_daily_digest(new_mods, updates, "2025-01-01")
    assert "New A" in text
    assert "Updated B" in text
    assert "2025-01-01" in text


class FakeRule:
    def __init__(self, notification_json):
        self.notification_json = notification_json


def test_notification_enabled_instant():
    rule = FakeRule('{"enabled": true, "mode": "instant", "channels": ["telegram", "discord"]}')
    nc = NotificationService.parse_notification_config(rule)
    assert nc.enabled is True
    assert nc.mode == "instant"
    assert nc.channels == ["telegram", "discord"]


def test_notification_disabled_skip():
    rule = FakeRule('{"enabled": false, "mode": "instant", "channels": ["telegram"]}')
    nc = NotificationService.parse_notification_config(rule)
    assert nc.enabled is False
    assert nc.mode == "instant"


def test_notification_daily_digest_mode():
    rule = FakeRule('{"enabled": true, "mode": "daily_digest", "channels": ["desktop"]}')
    nc = NotificationService.parse_notification_config(rule)
    assert nc.enabled is True
    assert nc.mode == "daily_digest"
    assert nc.channels == ["desktop"]


def test_notification_no_json_config_default():
    rule = FakeRule("{}")
    nc = NotificationService.parse_notification_config(rule)
    assert nc.enabled is False
    assert nc.mode == "daily_digest"
    assert nc.channels == []


def test_notification_malformed_json_shape_defaults():
    nc = NotificationService.parse_notification_config(FakeRule("[]"))
    assert nc.enabled is False
    assert nc.mode == "daily_digest"
    assert nc.channels == []


@pytest.mark.asyncio
async def test_notify_new_mods_respects_telegram_channel(service, session, monkeypatch):
    telegram = AsyncMock(return_value=DeliveryResult(True))
    discord = AsyncMock(return_value=DeliveryResult(True))
    monkeypatch.setattr(service, "send_telegram_message_result", telegram)
    monkeypatch.setattr(service, "send_discord_webhook_result", discord)
    nc = NotificationService.parse_notification_config(
        FakeRule('{"enabled": true, "mode": "instant", "channels": ["telegram"]}')
    )

    result = await service.notify_new_mods([{"title": "New A", "url": "https://example.com/a"}], "Rule A", nc)
    records = session.exec(select(Notification)).all()

    assert result["telegram_ok"] is True
    assert result["discord_ok"] is True
    assert result["notified_count"] == 1
    telegram.assert_awaited_once()
    discord.assert_not_awaited()
    assert [record.channel for record in records] == ["telegram"]


@pytest.mark.asyncio
async def test_notify_new_mods_escapes_html_message(service, monkeypatch):
    telegram = AsyncMock(return_value=DeliveryResult(True))
    discord = AsyncMock(return_value=DeliveryResult(True))
    monkeypatch.setattr(service, "send_telegram_message_result", telegram)
    monkeypatch.setattr(service, "send_discord_webhook_result", discord)
    nc = NotificationService.parse_notification_config(
        FakeRule('{"enabled": true, "mode": "instant", "channels": ["telegram"]}')
    )

    await service.notify_new_mods(
        [
            {
                "title": "Bad <Mod>",
                "url": "https://example.com/a?x='y'",
            },
            {
                "title": "No Link <Only>",
                "url": "javascript:alert(1)",
            },
        ],
        "Rule <A>",
        nc,
    )

    message = telegram.await_args.args[0]
    assert "Rule &lt;A&gt;" in message
    assert "Bad &lt;Mod&gt;" in message
    assert 'href="https://example.com/a?x=&#x27;y&#x27;"' in message
    assert "No Link &lt;Only&gt;" in message
    assert "javascript:alert" not in message
    discord.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_new_mods_respects_discord_channel(service, session, monkeypatch):
    telegram = AsyncMock(return_value=DeliveryResult(True))
    discord = AsyncMock(return_value=DeliveryResult(True))
    monkeypatch.setattr(service, "send_telegram_message_result", telegram)
    monkeypatch.setattr(service, "send_discord_webhook_result", discord)
    nc = NotificationService.parse_notification_config(
        FakeRule('{"enabled": true, "mode": "instant", "channels": ["discord"]}')
    )

    result = await service.notify_new_mods([{"title": "New A", "url": "https://example.com/a"}], "Rule A", nc)
    records = session.exec(select(Notification)).all()

    assert result["telegram_ok"] is True
    assert result["discord_ok"] is True
    assert result["notified_count"] == 1
    telegram.assert_not_awaited()
    discord.assert_awaited_once()
    assert [record.channel for record in records] == ["discord"]


@pytest.mark.asyncio
async def test_notify_new_mods_desktop_only_skips_external_channels(service, session, monkeypatch):
    telegram = AsyncMock(return_value=DeliveryResult(True))
    discord = AsyncMock(return_value=DeliveryResult(True))
    monkeypatch.setattr(service, "send_telegram_message_result", telegram)
    monkeypatch.setattr(service, "send_discord_webhook_result", discord)
    nc = NotificationService.parse_notification_config(
        FakeRule('{"enabled": true, "mode": "instant", "channels": ["desktop"]}')
    )

    result = await service.notify_new_mods([{"title": "New A", "url": "https://example.com/a"}], "Rule A", nc)
    records = session.exec(select(Notification)).all()

    assert result["telegram_ok"] is True
    assert result["discord_ok"] is True
    assert result["notified_count"] == 0
    telegram.assert_not_awaited()
    discord.assert_not_awaited()
    assert records == []


@pytest.mark.asyncio
async def test_notify_new_mods_records_skipped_channel_reason(service, session, monkeypatch):
    telegram = AsyncMock(return_value=DeliveryResult(False, "Telegram notification is disabled", skipped=True))
    discord = AsyncMock(return_value=DeliveryResult(True))
    monkeypatch.setattr(service, "send_telegram_message_result", telegram)
    monkeypatch.setattr(service, "send_discord_webhook_result", discord)
    nc = NotificationService.parse_notification_config(
        FakeRule('{"enabled": true, "mode": "instant", "channels": ["telegram"]}')
    )

    result = await service.notify_new_mods([{"title": "New A", "url": "https://example.com/a"}], "Rule A", nc)
    records = session.exec(select(Notification)).all()

    assert result["telegram_ok"] is False
    assert result["discord_ok"] is True
    assert result["notified_count"] == 0
    assert len(records) == 1
    assert records[0].status == "skipped"
    assert records[0].error_message == "Telegram notification is disabled"


@pytest.mark.asyncio
async def test_notify_updates_does_not_count_skipped_channels_as_sent(service, session, monkeypatch):
    from app.models.favorite import Favorite
    from app.models.mod import Mod
    from app.models.update_event import ModUpdateEvent

    mod = Mod(
        source="nexusmods",
        external_id="1001",
        game="skyrim",
        title="Updated Mod",
        url="https://example.com/mod",
        first_seen_at="2025-01-01T00:00:00+00:00",
        last_seen_at="2025-01-01T00:00:00+00:00",
    )
    session.add(mod)
    session.commit()
    session.refresh(mod)
    favorite = Favorite(
        mod_id=mod.id,
        notify_on_update=True,
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:00+00:00",
    )
    session.add(favorite)
    session.commit()
    session.refresh(favorite)
    event = ModUpdateEvent(
        mod_id=mod.id,
        favorite_id=favorite.id,
        old_version="1.0",
        new_version="2.0",
        detected_at="2025-01-02T00:00:00+00:00",
        seen=False,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    telegram = AsyncMock(return_value=DeliveryResult(False, "Telegram disabled", skipped=True))
    discord = AsyncMock(return_value=DeliveryResult(False, "Discord disabled", skipped=True))
    monkeypatch.setattr(service, "send_telegram_message_result", telegram)
    monkeypatch.setattr(service, "send_discord_webhook_result", discord)

    result = await service.notify_updates([event])

    assert result["telegram_ok"] is False
    assert result["discord_ok"] is False
    assert result["notified_count"] == 0

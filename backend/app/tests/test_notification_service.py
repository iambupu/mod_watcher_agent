import pytest
from unittest.mock import AsyncMock, patch
from sqlmodel import Session, SQLModel, create_engine
from app.services.notification_service import NotificationService
from app.models.notification import Notification
from app.models.favorite import Favorite
from app.models.mod import Mod


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

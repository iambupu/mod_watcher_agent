import logging
from dataclasses import dataclass
from datetime import UTC
from html import escape
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session

from app.logger import redact_sensitive_text
from app.schemas.watch_rule import NotificationConfig
from app.utils.boolean import parse_bool
from app.utils.json import json_object

logger = logging.getLogger(__name__)


EXTERNAL_NOTIFICATION_CHANNELS = {"telegram", "discord"}


@dataclass
class DeliveryResult:
    ok: bool
    reason: str | None = None
    skipped: bool = False


def _is_http_url(url: str) -> bool:
    """判断内部条件是否成立。"""
    try:
        return urlsplit(url).scheme in {"http", "https"}
    except ValueError:
        return False


def _record_status_for_delivery(result: DeliveryResult) -> str:
    if result.ok:
        return "sent"
    if result.skipped:
        return "skipped"
    return "failed"


class NotificationService:
    """Service for sending notifications via Telegram and Discord."""

    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session
    
    async def _send_and_record(
        self,
        subject: str,
        text: str,
        channels: list[str] | None = None,
    ) -> tuple[bool, bool]:
        """发送内部通知或外部请求。"""
        selected = EXTERNAL_NOTIFICATION_CHANNELS if channels is None else set(channels) & EXTERNAL_NOTIFICATION_CHANNELS
        telegram_ok = False
        discord_ok = False
        if "telegram" in selected:
            telegram_result = await self.send_telegram_message_result(text)
            telegram_ok = telegram_result.ok
            await self._record(
                "telegram",
                "chat",
                subject,
                text,
                _record_status_for_delivery(telegram_result),
                telegram_result.reason,
            )
        if "discord" in selected:
            discord_result = await self.send_discord_webhook_result(text)
            discord_ok = discord_result.ok
            await self._record(
                "discord",
                "webhook",
                subject,
                text,
                _record_status_for_delivery(discord_result),
                discord_result.reason,
            )
        return telegram_ok, discord_ok

    async def send_telegram_message(self, text: str) -> bool:
        """发送通知或外部请求。"""
        return (await self.send_telegram_message_result(text)).ok

    async def send_telegram_message_result(self, text: str) -> DeliveryResult:
        """发送通知或外部请求。"""
        from app.services.settings_service import SettingsService
        svc = SettingsService(self.session)
        if not parse_bool(svc.get("notifications_enabled"), default=True):
            return DeliveryResult(False, "Notification delivery is disabled", skipped=True)
        if not parse_bool(svc.get("telegram_enabled"), default=True):
            return DeliveryResult(False, "Telegram notification is disabled", skipped=True)
        from app.config import settings
        token = svc.get("telegram_bot_token") or settings.TELEGRAM_BOT_TOKEN
        chat_id = svc.get("telegram_chat_id") or settings.TELEGRAM_CHAT_ID
        if not token or not chat_id:
            return DeliveryResult(False, "Telegram bot token or chat ID is not configured", skipped=True)
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(url, json=payload)
                if resp.is_success:
                    return DeliveryResult(True)
                return DeliveryResult(False, f"Telegram returned HTTP {resp.status_code}")
            except Exception as e:
                logger.warning("Telegram send failed: %s", e)
                return DeliveryResult(False, f"Telegram send failed: {e}")

    async def send_discord_webhook(self, content: str) -> bool:
        """发送通知或外部请求。"""
        return (await self.send_discord_webhook_result(content)).ok

    async def send_discord_webhook_result(self, content: str) -> DeliveryResult:
        """发送通知或外部请求。"""
        from app.services.settings_service import SettingsService
        svc = SettingsService(self.session)
        if not parse_bool(svc.get("notifications_enabled"), default=True):
            return DeliveryResult(False, "Notification delivery is disabled", skipped=True)
        if not parse_bool(svc.get("discord_enabled"), default=True):
            return DeliveryResult(False, "Discord notification is disabled", skipped=True)
        from app.config import settings
        url = svc.get("discord_webhook_url") or settings.DISCORD_WEBHOOK_URL
        if not url:
            return DeliveryResult(False, "Discord webhook URL is not configured", skipped=True)
        payload = {"content": content, "username": "Mod Watcher"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(url, json=payload)
                if resp.is_success:
                    return DeliveryResult(True)
                return DeliveryResult(False, f"Discord returned HTTP {resp.status_code}")
            except Exception as e:
                logger.warning("Discord webhook failed: %s", e)
                return DeliveryResult(False, f"Discord webhook failed: {e}")

    async def send_external_channels(self, text: str) -> tuple[DeliveryResult, DeliveryResult]:
        """发送通知或外部请求。"""
        telegram = await self.send_telegram_message_result(text)
        discord = await self.send_discord_webhook_result(text)
        return telegram, discord

    @staticmethod
    def combined_delivery_status(results: list[DeliveryResult]) -> tuple[str, str | None]:
        """处理当前模块的业务逻辑并返回结果。"""
        if any(result.ok for result in results):
            return "sent", None
        reasons = [result.reason for result in results if result.reason]
        message = "; ".join(dict.fromkeys(reasons)) if reasons else None
        if results and all(result.skipped for result in results):
            return "skipped", message or "No notification channel is enabled or configured"
        return "failed", message

    async def _record(self, channel, recipient, subject, body, status, error_message=None):
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        from datetime import datetime

        from app.models.notification import Notification
        now = datetime.now(UTC).isoformat()
        n = Notification(channel=channel, recipient=recipient, subject=subject, body=redact_sensitive_text(str(body)),
                         status=status, error_message=redact_sensitive_text(str(error_message)) if error_message else None,
                         sent_at=now if status == "sent" else None, created_at=now)
        self.session.add(n)
        self.session.commit()

    @staticmethod
    def format_update_notification(mod_title, old_version, new_version, url):
        """格式化展示或通知文本。"""
        title = escape(str(mod_title or "Unknown"), quote=False)
        old = escape(str(old_version or "?"), quote=False)
        new = escape(str(new_version or "?"), quote=False)
        safe_url = escape(str(url or ""), quote=False)
        return f"\U0001f514 <b>{title}</b> \u5df2\u66f4\u65b0\uff01\n\U0001f4e6 \u7248\u672c: {old} \u2192 {new}\n\U0001f517 {safe_url}"

    @staticmethod
    def format_daily_digest(new_mods, updates, date_str):
        """格式化展示或通知文本。"""
        lines = [f"\U0001f4cb <b>Mod Watcher \u6bcf\u65e5\u6c47\u603b</b> ({date_str})", "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"]
        if new_mods:
            lines.append(f"\U0001f195 \u65b0\u53d1\u73b0 Mod: {len(new_mods)} \u4e2a")
            for m in new_mods[:5]:
                dl = m.get("downloads", 0) or 0
                ed = m.get("endorsements", 0) or 0
                lines.append(f"  \u2022 {m['title']} ({dl} DL, {ed} End)")
        if updates:
            lines.append(f"\U0001f504 \u6536\u85cf\u66f4\u65b0: {len(updates)} \u4e2a")
            for u in updates[:5]:
                ov = u.get("old_version") or "?"
                nv = u.get("new_version") or "?"
                lines.append(f"  \u2022 {u['mod_title']}: {ov} \u2192 {nv}")
        if not new_mods and not updates:
            lines.append("\u4eca\u65e5\u65e0\u65b0\u5185\u5bb9\u3002")
        return "\n".join(lines)

    @staticmethod
    def parse_notification_config(rule):
        """解析输入内容并返回结构化结果。"""
        data = json_object(getattr(rule, "notification_json", None))
        return NotificationConfig(**data)

    async def notify_new_mods(self, mods, rule_name, notification_config=None):
        """处理当前模块的业务逻辑并返回结果。"""
        if not mods:
            return {"telegram_ok": True, "discord_ok": True, "notified_count": 0}
        channels = None
        if notification_config is not None:
            channels = [channel for channel in notification_config.channels if channel in EXTERNAL_NOTIFICATION_CHANNELS]
        safe_rule_name = escape(str(rule_name), quote=False)
        lines = [f"\U0001f195 <b>\u65b0 Mod \u53d1\u73b0</b> \u2014 \u89c4\u5219: {safe_rule_name}", f"\u5171 {len(mods)} \u4e2a:", ""]
        for m in mods[:5]:
            title = escape(str(m.get("title") or "Unknown"), quote=False)
            url = str(m.get("url") or "")
            if _is_http_url(url):
                safe_url = escape(url, quote=True)
                lines.append(f'\u2022 <a href="{safe_url}">{title}</a>')
            else:
                lines.append(f"\u2022 {title}")
        text = "\n".join(lines)
        tg, dc = await self._send_and_record(f"New Mods: rule={rule_name}", text, channels=channels)
        selected = EXTERNAL_NOTIFICATION_CHANNELS if channels is None else set(channels) & EXTERNAL_NOTIFICATION_CHANNELS
        return {
            "telegram_ok": tg if "telegram" in selected else True,
            "discord_ok": dc if "discord" in selected else True,
            "notified_count": len(mods) if (tg or dc) else 0,
        }

    async def notify_updates(self, events):
        """处理当前模块的业务逻辑并返回结果。"""
        from app.models.favorite import Favorite
        from app.models.mod import Mod
        telegram_ok, discord_ok = True, True
        notified = 0
        for evt in events:
            fav = self.session.get(Favorite, evt.favorite_id) if hasattr(evt, "favorite_id") else None
            mod = self.session.get(Mod, evt.mod_id)
            title = mod.title if mod else "Unknown"
            url = mod.url if mod else ""
            text = self.format_update_notification(title, getattr(evt, "old_version", None), getattr(evt, "new_version", None), url)
            if fav and fav.notify_on_update:
                tg, dc = await self._send_and_record(f"Update: {title}", text)
                if not tg:
                    telegram_ok = False
                if not dc:
                    discord_ok = False
                if tg or dc:
                    notified += 1
        return {"telegram_ok": telegram_ok, "discord_ok": discord_ok, "notified_count": notified}

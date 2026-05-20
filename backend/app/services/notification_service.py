import logging
from datetime import UTC

import httpx
from sqlmodel import Session

from app.logger import redact_sensitive_text

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications via Telegram and Discord."""

    def __init__(self, session: Session):
        self.session = session
    
    async def _send_and_record(
        self,
        subject: str,
        text: str,
        channels: list[str] | None = None,
    ) -> tuple[bool, bool]:
        selected = set(["telegram", "discord"] if channels is None else channels)
        telegram_ok = False
        discord_ok = False
        if "telegram" in selected:
            telegram_ok = await self.send_telegram_message(text)
            await self._record(
                "telegram",
                "chat",
                subject,
                text,
                "sent" if telegram_ok else "failed",
            )
        if "discord" in selected:
            discord_ok = await self.send_discord_webhook(text)
            await self._record(
                "discord",
                "webhook",
                subject,
                text,
                "sent" if discord_ok else "failed",
            )
        return telegram_ok, discord_ok

    async def send_telegram_message(self, text: str) -> bool:
        from app.services.settings_service import SettingsService
        svc = SettingsService(self.session)
        if svc.get("notifications_enabled") == "false":
            return False
        from app.config import settings
        token = svc.get("telegram_bot_token") or settings.TELEGRAM_BOT_TOKEN
        chat_id = svc.get("telegram_chat_id") or settings.TELEGRAM_CHAT_ID
        if not token or not chat_id:
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(url, json=payload)
                return resp.is_success
            except Exception as e:
                logger.warning("Telegram send failed: %s", e)
                return False

    async def send_discord_webhook(self, content: str) -> bool:
        from app.services.settings_service import SettingsService
        svc = SettingsService(self.session)
        if svc.get("notifications_enabled") == "false":
            return False
        from app.config import settings
        url = svc.get("discord_webhook_url") or settings.DISCORD_WEBHOOK_URL
        if not url:
            return False
        payload = {"content": content, "username": "Mod Watcher"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(url, json=payload)
                return resp.is_success
            except Exception as e:
                logger.warning("Discord webhook failed: %s", e)
                return False

    async def _record(self, channel, recipient, subject, body, status, error_message=None):
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
        old = old_version or "?"
        new = new_version or "?"
        return f"\U0001f514 <b>{mod_title}</b> \u5df2\u66f4\u65b0\uff01\n\U0001f4e6 \u7248\u672c: {old} \u2192 {new}\n\U0001f517 {url}"

    @staticmethod
    def format_daily_digest(new_mods, updates, date_str):
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
        import json

        from app.schemas.watch_rule import NotificationConfig
        try:
            data = json.loads(rule.notification_json) if hasattr(rule, "notification_json") else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        return NotificationConfig(**data)

    async def notify_new_mods(self, mods, rule_name, notification_config=None):
        if not mods:
            return {"telegram_ok": True, "discord_ok": True, "notified_count": 0}
        channels = None
        if notification_config is not None:
            channels = [channel for channel in notification_config.channels if channel in {"telegram", "discord"}]
        lines = [f"\U0001f195 <b>\u65b0 Mod \u53d1\u73b0</b> \u2014 \u89c4\u5219: {rule_name}", f"\u5171 {len(mods)} \u4e2a:", ""]
        for m in mods[:5]:
            lines.append(f"\u2022 <a href='{m.get('url', '')}'>{m.get('title', 'Unknown')}</a>")
        text = "\n".join(lines)
        tg, dc = await self._send_and_record(f"New Mods: rule={rule_name}", text, channels=channels)
        selected = set(["telegram", "discord"] if channels is None else channels)
        return {
            "telegram_ok": tg if "telegram" in selected else True,
            "discord_ok": dc if "discord" in selected else True,
            "notified_count": len(mods) if (tg or dc) else 0,
        }

    async def notify_updates(self, events):
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
                notified += 1
        return {"telegram_ok": telegram_ok, "discord_ok": discord_ok, "notified_count": notified}

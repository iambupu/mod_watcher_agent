"""Job: Compile and send daily digest notifications.

Triggers: On schedule (daily at 9 AM via DIGEST_CRON env var: defaults to "0 9 * * *").
"""

import logging
from datetime import datetime, timezone, timedelta

from sqlmodel import Session, select

from app.db import engine
from app.models.mod import Mod
from app.models.update_event import ModUpdateEvent
from app.services.notification_service import NotificationService
from app.services.system_notification_service import SystemNotificationService

logger = logging.getLogger(__name__)


async def send_digest() -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    since_str = since.isoformat()
    date_str = now.strftime("%Y-%m-%d")
    results = {"telegram_ok": False, "discord_ok": False}

    with Session(engine) as session:
        notification = NotificationService(session)

        new_mods = session.exec(
            select(Mod).where(Mod.first_seen_at >= since_str, Mod.ignored == False)
        ).all()

        update_events = session.exec(
            select(ModUpdateEvent, Mod)
            .join(Mod, ModUpdateEvent.mod_id == Mod.id)
            .where(ModUpdateEvent.detected_at >= since_str, ModUpdateEvent.seen == False)
            .order_by(ModUpdateEvent.detected_at.desc())
        ).all()

        updates_list = []
        for event, mod in update_events:
            updates_list.append({
                "mod_title": mod.title,
                "old_version": event.old_version,
                "new_version": event.new_version,
                "url": mod.url,
            })

        new_list = []
        for mod in new_mods:
            new_list.append({"title": mod.title, "downloads": mod.downloads, "endorsements": mod.endorsements})

        if not new_list and not updates_list:
            logger.info("No new content for daily digest (%s)", date_str)
            SystemNotificationService(session).create_event(
                event_type="digest_complete",
                title="每日汇总完成",
                message="今日无新内容",
            )
            return {"telegram_ok": True, "discord_ok": True, "new_count": 0, "update_count": 0}

        body = NotificationService.format_daily_digest(new_list, updates_list, date_str)
        subject = f"Mod Watcher Daily Digest ({date_str})"

        results["telegram_ok"] = await notification.send_telegram_message(body)
        results["discord_ok"] = await notification.send_discord_webhook(body)

        await notification._record("all", "digest", subject, body, "sent" if (results["telegram_ok"] or results["discord_ok"]) else "failed")

        results["new_count"] = len(new_list)
        results["update_count"] = len(updates_list)

        SystemNotificationService(session).create_event(
            event_type="digest_complete",
            title="每日汇总完成",
            message=f"今日汇总: {results['new_count']} 个新 Mod，{results['update_count']} 个收藏更新",
        )

        return results

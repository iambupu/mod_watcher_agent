import logging
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models.system_notification import SystemNotificationEvent
from app.services.settings_service import SettingsService
from app.services.windows_notifier import send_windows_notification
from app.utils.boolean import parse_bool
from app.utils.ids import positive_integer_ids

logger = logging.getLogger(__name__)

DESKTOP_DISPATCH_EVENT_TYPES = {
    "daily_digest_complete",
    "weekly_digest_complete",
    "llm_summary_report_complete",
    "job_failed",
}


class SystemNotificationService:

    def __init__(self, session: Session):
        """保存数据库会话，用于创建和查询系统通知事件。"""
        self.session = session

    def create_event(
        self,
        event_type: str,
        title: str,
        message: str,
        mod_id: int | None = None,
        related_url: str | None = None,
    ) -> SystemNotificationEvent:
        """创建系统通知事件，符合配置时立即尝试派发桌面通知。"""
        now = datetime.now(UTC).isoformat()
        event = SystemNotificationEvent(
            event_type=event_type,
            title=title,
            message=message,
            mod_id=mod_id,
            related_url=related_url,
            created_at=now,
        )
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        if (
            event_type in DESKTOP_DISPATCH_EVENT_TYPES
            and self._desktop_notifications_enabled()
            and send_windows_notification(title, message)
        ):
            event.seen = True
            self.session.add(event)
            self.session.commit()
        return event

    def _desktop_notifications_enabled(self) -> bool:
        """读取全局通知开关和系统通知开关。"""
        settings = SettingsService(self.session)
        return (
            parse_bool(settings.get("notifications_enabled"), default=True)
            and parse_bool(settings.get("system_notifications_enabled"), default=True)
        )

    def get_recent_events(
        self, since_id: int = 0, limit: int = 50
    ) -> list[SystemNotificationEvent]:
        """读取指定 ID 之后的最近系统通知事件。"""
        stmt = (
            select(SystemNotificationEvent)
            .where(SystemNotificationEvent.id > since_id)
            .order_by(SystemNotificationEvent.id.desc())
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())

    def mark_seen(self, event_ids: list[int]) -> int:
        """批量标记系统通知为已读，并返回实际更新数量。"""
        deduped_ids = positive_integer_ids(event_ids)
        if not deduped_ids:
            return 0
        stmt = select(SystemNotificationEvent).where(
            SystemNotificationEvent.id.in_(deduped_ids)
        )
        events = self.session.exec(stmt).all()
        updated = 0
        for event in events:
            if not event.seen:
                event.seen = True
                self.session.add(event)
                updated += 1
        self.session.commit()
        return updated

    def get_unseen_events_by_ids(
        self,
        event_ids: list[int],
        limit: int = 50,
    ) -> list[SystemNotificationEvent]:
        """按 ID 读取仍未读的系统通知，用于手动桌面派发。"""
        deduped_ids = positive_integer_ids(event_ids)
        if not deduped_ids:
            return []
        stmt = (
            select(SystemNotificationEvent)
            .where(
                SystemNotificationEvent.id.in_(deduped_ids),
                SystemNotificationEvent.seen.is_(False),
            )
            .order_by(SystemNotificationEvent.id.asc())
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())

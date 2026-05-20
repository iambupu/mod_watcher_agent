import logging
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models.system_notification import SystemNotificationEvent
from app.services.settings_service import SettingsService
from app.services.windows_notifier import send_windows_notification

logger = logging.getLogger(__name__)

DESKTOP_DISPATCH_EVENT_TYPES = {
    "daily_digest_complete",
    "weekly_digest_complete",
    "llm_summary_report_complete",
    "job_failed",
}


class SystemNotificationService:

    def __init__(self, session: Session):
        self.session = session

    def create_event(
        self,
        event_type: str,
        title: str,
        message: str,
        mod_id: int | None = None,
        related_url: str | None = None,
    ) -> SystemNotificationEvent:
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
        settings = SettingsService(self.session)
        return (
            settings.get("notifications_enabled") != "false"
            and settings.get("system_notifications_enabled") != "false"
        )

    def get_recent_events(
        self, since_id: int = 0, limit: int = 50
    ) -> list[SystemNotificationEvent]:
        stmt = (
            select(SystemNotificationEvent)
            .where(SystemNotificationEvent.id > since_id)
            .order_by(SystemNotificationEvent.id.desc())
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())

    def mark_seen(self, event_ids: list[int]) -> int:
        stmt = select(SystemNotificationEvent).where(
            SystemNotificationEvent.id.in_(event_ids)
        )
        events = self.session.exec(stmt).all()
        updated = 0
        for event in events:
            event.seen = True
            updated += 1
        self.session.commit()
        return updated

    def get_unseen_events_by_ids(
        self,
        event_ids: list[int],
        limit: int = 50,
    ) -> list[SystemNotificationEvent]:
        if not event_ids:
            return []
        deduped_ids = sorted({event_id for event_id in event_ids if event_id > 0})
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

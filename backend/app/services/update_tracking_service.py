from sqlmodel import Session, func, select

from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.update_event import ModUpdateEvent


class UpdateTrackingService:
    """Dedicated service for querying and managing update events."""

    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session

    def get_events(
        self,
        mod_id: int | None = None,
        favorite_id: int | None = None,
        seen: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ModUpdateEvent], int]:
        """Query update events with optional filters. Returns (items, total)."""
        query = select(ModUpdateEvent)
        count_query = select(func.count()).select_from(ModUpdateEvent)

        if mod_id is not None:
            query = query.where(ModUpdateEvent.mod_id == mod_id)
            count_query = count_query.where(ModUpdateEvent.mod_id == mod_id)
        if favorite_id is not None:
            query = query.where(ModUpdateEvent.favorite_id == favorite_id)
            count_query = count_query.where(ModUpdateEvent.favorite_id == favorite_id)
        if seen is not None:
            query = query.where(ModUpdateEvent.seen == seen)
            count_query = count_query.where(ModUpdateEvent.seen == seen)

        total = int(self.session.exec(count_query).one() or 0)
        query = query.order_by(ModUpdateEvent.detected_at.desc()).offset(offset).limit(limit)
        items = self.session.exec(query).all()
        return items, total

    def mark_seen(self, event_id: int) -> ModUpdateEvent:
        """Mark an update event as seen."""
        event = self.session.get(ModUpdateEvent, event_id)
        if event is None:
            raise ValueError(f"UpdateEvent id={event_id} not found")
        event.seen = True
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return event

    def mark_all_seen(self) -> int:
        """Mark all unseen update events as seen and return updated count."""
        events = self.session.exec(
            select(ModUpdateEvent).where(ModUpdateEvent.seen == False)  # noqa: E712
        ).all()
        for event in events:
            event.seen = True
            self.session.add(event)
        self.session.commit()
        return len(events)

    def get_unseen_count(self) -> int:
        """Get count of unseen update events."""
        query = (
            select(func.count())
            .select_from(ModUpdateEvent)
            .where(ModUpdateEvent.seen == False)  # noqa: E712
        )
        return int(self.session.exec(query).one() or 0)


def record_favorite_metadata_update(
    session: Session,
    mod: Mod,
    *,
    new_version: str | None,
    new_updated_at: str | None,
    detected_at: str,
) -> ModUpdateEvent | None:
    """Record an update when a metadata refresh advances a favorited mod."""
    if mod.id is None:
        return None
    favorite = session.exec(select(Favorite).where(Favorite.mod_id == mod.id)).first()
    if favorite is None:
        return None

    old_version = favorite.last_known_version
    old_updated_at = favorite.last_known_updated_at
    version_changed = bool(new_version) and new_version != old_version
    updated_at_changed = bool(new_updated_at) and new_updated_at != old_updated_at
    if not version_changed and not updated_at_changed:
        return None

    event = ModUpdateEvent(
        mod_id=mod.id,
        favorite_id=favorite.id,
        old_version=old_version,
        new_version=new_version or old_version,
        old_updated_at=old_updated_at,
        new_updated_at=new_updated_at or old_updated_at,
        detected_at=detected_at,
        seen=False,
    )
    favorite.last_known_version = new_version or old_version
    favorite.last_known_updated_at = new_updated_at or old_updated_at
    favorite.last_checked_at = detected_at
    session.add(event)
    session.add(favorite)
    return event

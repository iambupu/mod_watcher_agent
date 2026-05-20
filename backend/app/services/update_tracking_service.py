from sqlmodel import Session, func, select

from app.models.update_event import ModUpdateEvent


class UpdateTrackingService:
    """Dedicated service for querying and managing update events."""

    def __init__(self, session: Session):
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

    def get_unseen_count(self) -> int:
        """Get count of unseen update events."""
        query = (
            select(func.count())
            .select_from(ModUpdateEvent)
            .where(ModUpdateEvent.seen == False)  # noqa: E712
        )
        return int(self.session.exec(query).one() or 0)

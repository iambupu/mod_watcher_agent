from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import get_session
from app.services.system_notification_service import SystemNotificationService
from app.services.windows_notifier import send_windows_notification

router = APIRouter(prefix="/api/system-notifications", tags=["system-notifications"])


class MarkSeenRequest(BaseModel):
    event_ids: list[int]


class DispatchRequest(BaseModel):
    event_ids: list[int] = Field(min_length=1, max_length=50)


@router.get("/recent")
def get_recent(
    since_id: int = Query(0, ge=0, description="Return events with id greater than this"),
    limit: int = Query(50, ge=1, le=500, description="Maximum events to return"),
    session: Session = Depends(get_session),
):
    svc = SystemNotificationService(session)
    events = svc.get_recent_events(since_id=since_id, limit=limit)
    return {
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "title": e.title,
                "message": e.message,
                "mod_id": e.mod_id,
                "related_url": e.related_url,
                "seen": e.seen,
                "created_at": e.created_at,
            }
            for e in events
        ]
    }


@router.post("/mark-seen")
def mark_seen(
    body: MarkSeenRequest,
    session: Session = Depends(get_session),
):
    svc = SystemNotificationService(session)
    updated = svc.mark_seen(body.event_ids)
    return {"updated": updated}


@router.post("/dispatch-windows")
def dispatch_windows(
    body: DispatchRequest,
    session: Session = Depends(get_session),
):
    svc = SystemNotificationService(session)
    events = svc.get_unseen_events_by_ids(body.event_ids, limit=50)
    dispatched_ids: list[int] = []
    for event in events:
        event_id = int(event.id or 0)
        title = str(event.title or "").strip()
        message = str(event.message or "").strip()
        if not title or not message:
            continue
        if send_windows_notification(title, message):
            dispatched_ids.append(event_id)
    return {"dispatched_ids": dispatched_ids}

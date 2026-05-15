from fastapi import APIRouter, Query, Depends
from sqlmodel import Session
from pydantic import BaseModel

from app.db import get_session
from app.services.system_notification_service import SystemNotificationService

router = APIRouter(prefix="/api/system-notifications", tags=["system-notifications"])


class MarkSeenRequest(BaseModel):
    event_ids: list[int]


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

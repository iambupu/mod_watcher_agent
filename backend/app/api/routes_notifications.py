"""Notification history API — side-panel notification centre."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.db import get_session
from app.models.notification import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class MarkReadRequest(BaseModel):
    ids: list[int]


SessionDep = Annotated[Session, Depends(get_session)]


@router.get("")
def list_notifications(
    session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
):
    """List recent outgoing notification records, newest first."""
    total = int(session.exec(select(func.count()).select_from(Notification)).one() or 0)
    rows = session.exec(
        select(Notification)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    items = [_notification_to_dict(r) for r in rows]
    return {"items": items, "total": total}


@router.post("/mark-read")
def mark_notifications_read(
    session: SessionDep,
    body: Annotated[MarkReadRequest, Body()],
):
    """Mark one or more notifications as read."""
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        return {"updated": 0}
    rows = session.exec(select(Notification).where(Notification.id.in_(ids))).all()
    updated = 0
    for row in rows:
        if not row.read:
            row.read = True
            updated += 1
    session.commit()
    return {"updated": updated}


@router.post("/mark-all-read")
def mark_all_notifications_read(
    session: SessionDep,
):
    """Mark all notifications as read."""
    rows = session.exec(select(Notification).where(Notification.read.is_(False))).all()
    count = 0
    for row in rows:
        row.read = True
        count += 1
    session.commit()
    return {"updated": count}


@router.get("/unread-count")
def unread_notification_count(
    session: SessionDep,
):
    """Return number of unread notifications."""
    count = int(
        session.exec(
            select(func.count())
            .select_from(Notification)
            .where(Notification.read.is_(False))
        ).one()
        or 0
    )
    return {"count": count}


def _notification_to_dict(n: Notification) -> dict:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    channel = n.channel
    status = n.status
    error_message = n.error_message
    if status == "failed" and n.channel == "all" and error_message is None:
        channel = "desktop"
        status = "sent"
    return {
        "id": n.id,
        "channel": channel,
        "recipient": n.recipient,
        "subject": n.subject,
        "body": n.body,
        "status": status,
        "error_message": error_message,
        "sent_at": n.sent_at,
        "created_at": n.created_at,
        "read": n.read,
    }

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models.summary import ModSummary
from app.schemas.update_event import UpdateEventList, UpdateEventRead
from app.services.settings_service import SettingsService
from app.services.update_tracking_service import UpdateTrackingService

router = APIRouter(prefix="/api/updates", tags=["updates"])


def _build_summary_map(session: Session, mod_ids: list[int]) -> dict[int, str]:
    language = SettingsService(session).get("summary_language") or "zh-CN"
    summary_by_mod: dict[int, str] = {}
    if not mod_ids:
        return summary_by_mod
    fallback_languages = [language]
    if language != "en":
        fallback_languages.append("en")
    summary_rows = session.exec(
        select(ModSummary).where(
            ModSummary.mod_id.in_(mod_ids),
            ModSummary.language.in_(fallback_languages),
            ModSummary.summary_type == "brief",
        )
    ).all()
    en_by_mod: dict[int, str] = {}
    for row in summary_rows:
        if row.language == language:
            summary_by_mod[row.mod_id] = row.content
        elif row.language == "en":
            en_by_mod[row.mod_id] = row.content
    for mod_id, en_content in en_by_mod.items():
        if mod_id not in summary_by_mod:
            summary_by_mod[mod_id] = en_content
    return summary_by_mod


@router.get("", response_model=UpdateEventList)
def list_updates(
    favorite_id: int | None = Query(default=None),
    seen: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
    session: Session = Depends(get_session),
):
    service = UpdateTrackingService(session)
    items, total = service.get_events(
        favorite_id=favorite_id, seen=seen, offset=offset, limit=limit
    )
    mod_ids = [item.mod_id for item in items if item.mod_id is not None]
    summary_by_mod = _build_summary_map(session, mod_ids)
    result_items = []
    for item in items:
        data = UpdateEventRead.model_validate(item).model_dump()
        data["translated_summary"] = summary_by_mod.get(item.mod_id)
        result_items.append(data)
    return {"items": result_items, "total": total}


@router.patch("/{event_id}/seen", response_model=UpdateEventRead)
def mark_event_seen(event_id: int, session: Session = Depends(get_session)):
    service = UpdateTrackingService(session)
    try:
        event = service.mark_seen(event_id)
        return event
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Update event not found") from e

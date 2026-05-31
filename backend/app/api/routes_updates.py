from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models.mod import Mod
from app.models.update_event import ModUpdateEvent
from app.schemas.mod import ModRead
from app.schemas.update_event import UpdateEventList, UpdateEventRead
from app.services.summary_service import load_preferred_brief_summary_map
from app.services.update_tracking_service import UpdateTrackingService

router = APIRouter(prefix="/api/updates", tags=["updates"])


def _build_mod_map(session: Session, mod_ids: list[int], summary_by_mod: dict[int, str]) -> dict[int, dict]:
    """构建内部流程需要的数据结构。"""
    if not mod_ids:
        return {}
    mods = session.exec(select(Mod).where(Mod.id.in_(mod_ids))).all()
    mod_by_id: dict[int, dict] = {}
    for mod in mods:
        if mod.id is None:
            continue
        data = ModRead.model_validate(mod).model_dump()
        data["translated_summary"] = summary_by_mod.get(mod.id) or data.get("translated_summary")
        mod_by_id[int(mod.id)] = data
    return mod_by_id


def _event_to_dict(item: ModUpdateEvent, mod_by_id: dict[int, dict], summary_by_mod: dict[int, str]) -> dict:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    data = UpdateEventRead.model_validate(item).model_dump()
    data["translated_summary"] = summary_by_mod.get(item.mod_id)
    data["mod"] = mod_by_id.get(item.mod_id)
    return data


@router.get("", response_model=UpdateEventList)
def list_updates(
    favorite_id: int | None = Query(default=None),
    seen: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """查询并返回列表数据。"""
    service = UpdateTrackingService(session)
    items, total = service.get_events(
        favorite_id=favorite_id, seen=seen, offset=offset, limit=limit
    )
    mod_ids = [item.mod_id for item in items if item.mod_id is not None]
    summary_by_mod = load_preferred_brief_summary_map(session, mod_ids)
    mod_by_id = _build_mod_map(session, mod_ids, summary_by_mod)
    result_items = [_event_to_dict(item, mod_by_id, summary_by_mod) for item in items]
    return {"items": result_items, "total": total}


@router.patch("/seen")
def mark_all_events_seen(session: Session = Depends(get_session)):
    """标记状态变更并返回结果。"""
    service = UpdateTrackingService(session)
    return {"updated": service.mark_all_seen()}


@router.patch("/{event_id}/seen", response_model=UpdateEventRead)
def mark_event_seen(event_id: int, session: Session = Depends(get_session)):
    """标记状态变更并返回结果。"""
    service = UpdateTrackingService(session)
    try:
        event = service.mark_seen(event_id)
        summary_by_mod = load_preferred_brief_summary_map(session, [event.mod_id])
        mod_by_id = _build_mod_map(session, [event.mod_id], summary_by_mod)
        return _event_to_dict(event, mod_by_id, summary_by_mod)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Update event not found") from e

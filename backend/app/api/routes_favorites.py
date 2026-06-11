from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.schemas.favorite import (
    FavoriteCreate,
    FavoriteImportCreate,
    FavoriteRead,
    FavoriteUpdate,
)
from app.schemas.update_event import UpdateEventRead
from app.services.favorite_service import FavoriteService
from app.services.summary_service import load_preferred_brief_summary_map

router = APIRouter(prefix="/api/favorites", tags=["favorites"])


def _favorite_to_read(
    session: Session,
    favorite: Favorite,
    summary_by_mod: dict[int, str] | None = None,
    mod_by_id: dict[int, Mod] | None = None,
) -> dict:
    """把收藏和关联 Mod 摘要打包成前端需要的 FavoriteRead 结构。"""
    data = FavoriteRead.model_validate(favorite).model_dump()
    mod = mod_by_id.get(favorite.mod_id) if mod_by_id is not None else session.get(Mod, favorite.mod_id)
    if mod is not None:
        mod_data = mod.model_dump()
        mod_data["translated_summary"] = (summary_by_mod or {}).get(favorite.mod_id)
        data["mod"] = mod_data
    data["translated_summary"] = (summary_by_mod or {}).get(favorite.mod_id)
    return data


def _check_update_response(favorite: Favorite, event) -> dict:
    return {
        "favorite_id": favorite.id,
        "mod_id": favorite.mod_id,
        "update_detected": event is not None,
        "update_event": UpdateEventRead.model_validate(event).model_dump() if event is not None else None,
        "last_checked_at": favorite.last_checked_at,
        "notification_sent": bool(getattr(event, "notification_sent", False)) if event is not None else False,
    }


@router.get("", response_model=list[FavoriteRead])
def list_favorites(
    detail: Literal["full", "refs"] = Query(default="full"),
    session: Session = Depends(get_session),
):
    """List all favorites."""
    FavoriteService(session).reconcile_local_metadata_updates()
    items = session.exec(select(Favorite).order_by(Favorite.created_at.desc())).all()
    if detail == "refs":
        return [FavoriteRead.model_validate(item).model_dump() for item in items]
    mod_ids = [item.mod_id for item in items if item.mod_id is not None]
    summary_by_mod = load_preferred_brief_summary_map(session, mod_ids)
    mods = session.exec(select(Mod).where(Mod.id.in_(mod_ids))).all() if mod_ids else []
    mod_by_id = {mod.id: mod for mod in mods if mod.id is not None}
    result = []
    for item in items:
        result.append(_favorite_to_read(session, item, summary_by_mod, mod_by_id))
    return result


@router.post("", response_model=FavoriteRead, status_code=201)
async def create_favorite(
    data: FavoriteCreate,
    session: Session = Depends(get_session),
):
    """Add a mod to favorites."""
    service = FavoriteService(session)
    try:
        fav = await service.add_favorite(data.mod_id, data.user_note)
        update_fields = {}
        explicit_fields = data.model_fields_set
        if "tracking_enabled" in explicit_fields:
            update_fields["tracking_enabled"] = data.tracking_enabled
        if "notify_on_update" in explicit_fields:
            update_fields["notify_on_update"] = data.notify_on_update
        if "user_tags_json" in explicit_fields:
            update_fields["user_tags_json"] = data.user_tags_json
        if "user_note" in explicit_fields:
            update_fields["user_note"] = data.user_note
        if update_fields:
            fav = await service.update_favorite(fav.id, **update_fields)
        summary_by_mod = load_preferred_brief_summary_map(session, [fav.mod_id])
        return _favorite_to_read(session, fav, summary_by_mod)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/import", response_model=FavoriteRead, status_code=201)
async def import_favorite(
    data: FavoriteImportCreate,
    session: Session = Depends(get_session),
):
    """Import the current browser page as a mod and add it to favorites."""
    service = FavoriteService(session)
    try:
        fav = await service.import_and_favorite(data)
        summary_by_mod = load_preferred_brief_summary_map(session, [fav.mod_id])
        return _favorite_to_read(session, fav, summary_by_mod)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{favorite_id}", response_model=FavoriteRead)
def get_favorite(
    favorite_id: int,
    session: Session = Depends(get_session),
):
    """Get a single favorite by ID."""
    FavoriteService(session).reconcile_local_metadata_updates()
    fav = session.get(Favorite, favorite_id)
    if fav is None:
        raise HTTPException(status_code=404, detail="Favorite not found")
    summary_by_mod = load_preferred_brief_summary_map(session, [fav.mod_id])
    return _favorite_to_read(session, fav, summary_by_mod)


@router.put("/{favorite_id}", response_model=FavoriteRead)
async def update_favorite(
    favorite_id: int,
    data: FavoriteUpdate,
    session: Session = Depends(get_session),
):
    """Update a favorite."""
    service = FavoriteService(session)
    try:
        update_dict = data.model_dump(exclude_unset=True)
        fav = await service.update_favorite(favorite_id, **update_dict)
        summary_by_mod = load_preferred_brief_summary_map(session, [fav.mod_id])
        return _favorite_to_read(session, fav, summary_by_mod)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Favorite not found") from e


@router.post("/{favorite_id}/check-update")
async def check_favorite_update(
    favorite_id: int,
    session: Session = Depends(get_session),
):
    """Check a single favorite for updates immediately."""
    service = FavoriteService(session)
    try:
        event = await service.check_update(favorite_id)
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail="Favorite not found") from e
        raise HTTPException(status_code=400, detail=detail) from e
    fav = session.get(Favorite, favorite_id)
    if fav is None:
        raise HTTPException(status_code=404, detail="Favorite not found")
    return _check_update_response(fav, event)


@router.delete("/{favorite_id}", status_code=204)
async def delete_favorite(
    favorite_id: int,
    session: Session = Depends(get_session),
):
    """Delete a favorite."""
    service = FavoriteService(session)
    try:
        await service.remove_favorite(favorite_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Favorite not found") from e

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.summary import ModSummary
from app.schemas.favorite import (
    FavoriteCreate,
    FavoriteRead,
    FavoriteUpdate,
)
from app.services.favorite_service import FavoriteService
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/favorites", tags=["favorites"])


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


def _favorite_to_read(
    session: Session,
    favorite: Favorite,
    summary_by_mod: dict[int, str] | None = None,
) -> dict:
    data = FavoriteRead.model_validate(favorite).model_dump()
    mod = session.get(Mod, favorite.mod_id)
    if mod is not None:
        mod_data = mod.model_dump()
        mod_data["translated_summary"] = (summary_by_mod or {}).get(favorite.mod_id)
        data["mod"] = mod_data
    data["translated_summary"] = (summary_by_mod or {}).get(favorite.mod_id)
    return data


@router.get("", response_model=list[FavoriteRead])
async def list_favorites(
    session: Session = Depends(get_session),
):
    """List all favorites."""
    items = session.exec(select(Favorite).order_by(Favorite.created_at.desc())).all()
    mod_ids = [item.mod_id for item in items if item.mod_id is not None]
    summary_by_mod = _build_summary_map(session, mod_ids)
    result = []
    for item in items:
        result.append(_favorite_to_read(session, item, summary_by_mod))
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
        if data.tracking_enabled is not None and not data.tracking_enabled:
            update_fields["tracking_enabled"] = data.tracking_enabled
        if data.notify_on_update is not None and not data.notify_on_update:
            update_fields["notify_on_update"] = data.notify_on_update
        if data.user_tags_json and data.user_tags_json != "[]":
            update_fields["user_tags_json"] = data.user_tags_json
        if update_fields:
            fav = await service.update_favorite(fav.id, **update_fields)
        summary_by_mod = _build_summary_map(session, [fav.mod_id])
        return _favorite_to_read(session, fav, summary_by_mod)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{favorite_id}", response_model=FavoriteRead)
async def get_favorite(
    favorite_id: int,
    session: Session = Depends(get_session),
):
    """Get a single favorite by ID."""
    fav = session.get(Favorite, favorite_id)
    if fav is None:
        raise HTTPException(status_code=404, detail="Favorite not found")
    summary_by_mod = _build_summary_map(session, [fav.mod_id])
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
        summary_by_mod = _build_summary_map(session, [fav.mod_id])
        return _favorite_to_read(session, fav, summary_by_mod)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Favorite not found") from e


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

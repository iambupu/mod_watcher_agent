import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlmodel import Session

from app.db import get_session
from app.schemas.mod import ModGameOption, ModList, ModRead
from app.services.mod_service import ModService
from app.services.summary_service import (
    run_missing_summaries_job,
    run_single_summary_job,
)

router = APIRouter(prefix="/api/mods", tags=["mods"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=ModList)
async def list_mods(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    game: str | None = Query(default=None),
    source: str | None = Query(default=None),
    search: str | None = Query(default=None),
    adult_content: Literal["include", "exclude", "only"] | None = Query(default=None),
    sort_by: str = Query(default="first_seen_at"),
    sort_order: str = Query(default="desc"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
):
    """List discovered mods with optional filters."""
    mod_service = ModService(session)
    displays, total, language, missing_ids = mod_service.list_mod_displays(
        game=game,
        source=source,
        search=search,
        adult_content=adult_content,
        sort_by=sort_by,
        sort_order=sort_order,
        offset=offset,
        limit=limit,
    )
    if missing_ids and mod_service.translation_enabled():
        background_tasks.add_task(run_missing_summaries_job, missing_ids, language)

    response_items = [ModRead.model_validate(item).model_dump() for item in displays]
    return ModList(items=response_items, total=total)


@router.get("/games", response_model=list[ModGameOption])
async def list_mod_games(
    session: SessionDep,
):
    """Return game filter options aggregated from the current mod list."""
    rows = ModService(session).list_game_options()
    options: list[ModGameOption] = []
    seen: set[str] = set()
    for game_domain, game_name, count in rows:
        value = game_domain or game_name
        label = game_name or game_domain
        if not value or not label or value in seen:
            continue
        seen.add(value)
        options.append(ModGameOption(value=value, label=label, count=count))
    return options


@router.get("/ignored", response_model=ModList)
async def list_ignored_mods(
    session: SessionDep,
    game: str | None = Query(default=None),
    source: str | None = Query(default=None),
    search: str | None = Query(default=None),
    adult_content: Literal["include", "exclude", "only"] | None = Query(default=None),
    sort_by: str = Query(default="first_seen_at"),
    sort_order: str = Query(default="desc"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
):
    """List ignored mods so users can restore them."""
    displays, total, _language, _missing_ids = ModService(session).list_mod_displays(
        game=game,
        source=source,
        search=search,
        adult_content=adult_content,
        sort_by=sort_by,
        sort_order=sort_order,
        offset=offset,
        limit=limit,
        ignored=True,
    )
    response_items = [ModRead.model_validate(item).model_dump() for item in displays]
    return ModList(items=response_items, total=total)


@router.get("/{mod_id}", response_model=ModRead)
async def get_mod(
    mod_id: int,
    session: SessionDep,
):
    """Get a single mod by ID."""
    display, _language = ModService(session).get_mod_display(mod_id)
    if display is None:
        raise HTTPException(status_code=404, detail="Mod not found")
    return ModRead.model_validate(display).model_dump()


@router.post("/{mod_id}/summary/regenerate")
async def regenerate_mod_summary(
    mod_id: int,
    session: SessionDep,
):
    """Regenerate the translated brief summary for a mod in the configured language."""
    mod_service = ModService(session)
    mod = mod_service.get_mod_or_none(mod_id)
    if mod is None:
        raise HTTPException(status_code=404, detail="Mod not found")
    language = mod_service.get_summary_language()
    mod_service.delete_summary_if_exists(mod_id, language, "brief")
    asyncio.create_task(run_single_summary_job(mod_id, language, "brief"))
    return {"status": "queued", "mod_id": mod_id, "language": language}


@router.post("/{mod_id}/introduction/generate")
async def generate_mod_introduction(
    mod_id: int,
    session: SessionDep,
):
    """Generate and persist a detailed AI introduction for a mod."""
    mod_service = ModService(session)
    mod = mod_service.get_mod_or_none(mod_id)
    if mod is None:
        raise HTTPException(status_code=404, detail="Mod not found")
    language = mod_service.get_summary_language()
    existing_content = mod_service.get_summary_content(mod_id, language, "introduction")
    if existing_content:
        return {
            "status": "cached",
            "mod_id": mod_id,
            "language": language,
            "content": existing_content,
        }
    await run_single_summary_job(mod_id, language, "introduction")
    return {
        "status": "generated",
        "mod_id": mod_id,
        "language": language,
        "content": mod_service.get_summary_content(mod_id, language, "introduction"),
    }


@router.post("/{mod_id}/ignore")
async def ignore_mod(
    mod_id: int,
    session: SessionDep,
):
    """Mark a mod as ignored."""
    if not ModService(session).mark_mod_ignored(mod_id):
        raise HTTPException(status_code=404, detail="Mod not found")
    return {"ignored": True}


@router.post("/{mod_id}/unignore")
async def unignore_mod(
    mod_id: int,
    session: SessionDep,
):
    """Restore an ignored mod to the visible mod list."""
    if not ModService(session).mark_mod_visible(mod_id):
        raise HTTPException(status_code=404, detail="Mod not found")
    return {"ignored": False}

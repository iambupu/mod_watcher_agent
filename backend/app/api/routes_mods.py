# 中文注释：声明Mod 列表与详情相关的 FastAPI 路由。

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlmodel import Session

from app.db import engine, get_session
from app.jobs.generate_summaries import (
    generate_single_summary_payload_locked,
    run_missing_summaries_job,
    run_single_summary_job,
)
from app.jobs.manual_jobs import create_job_run, enqueue_job_run
from app.schemas.mod import ModCategoryOption, ModGameOption, ModList, ModRead
from app.services.mod_service import ModService

router = APIRouter(prefix="/api/mods", tags=["mods"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=ModList)
def list_mods(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    game: str | None = Query(default=None),
    source: str | None = Query(default=None),
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    content_language: str | None = Query(default=None),
    adult_content: Literal["include", "exclude", "only"] | None = Query(default=None),
    sort_by: str = Query(default="first_seen_at"),
    sort_order: str = Query(default="desc"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    """List discovered mods with optional filters."""
    mod_service = ModService(session)
    displays, total, language, missing_ids = mod_service.list_mod_displays(
        game=game,
        source=source,
        category=category,
        search=search,
        content_language=content_language,
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
def list_mod_games(
    session: SessionDep,
):
    """Return game filter options aggregated from the current mod list."""
    rows = ModService(session).list_game_options()
    merged: dict[str, ModGameOption] = {}
    for game_domain, game_name, count in rows:
        value = game_name if game_domain == "loverslab" else game_domain or game_name
        label = game_name or game_domain
        if not value or not label:
            continue
        if value in merged:
            existing = merged[value]
            merged[value] = ModGameOption(
                value=existing.value,
                label=existing.label,
                count=existing.count + count,
            )
        else:
            merged[value] = ModGameOption(value=value, label=label, count=count)
    return sorted(merged.values(), key=lambda option: (-option.count, option.label))


@router.get("/categories", response_model=list[ModCategoryOption])
def list_mod_categories(
    session: SessionDep,
):
    """Return category filter options aggregated from the current mod list."""
    rows = ModService(session).list_category_options()
    return [
        ModCategoryOption(value=category, label=category, count=count)
        for category, count in rows
        if category
    ]


@router.get("/ignored", response_model=ModList)
def list_ignored_mods(
    session: SessionDep,
    game: str | None = Query(default=None),
    source: str | None = Query(default=None),
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    content_language: str | None = Query(default=None),
    adult_content: Literal["include", "exclude", "only"] | None = Query(default=None),
    sort_by: str = Query(default="first_seen_at"),
    sort_order: str = Query(default="desc"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    """List ignored mods so users can restore them."""
    displays, total, _language, _missing_ids = ModService(session).list_mod_displays(
        game=game,
        source=source,
        category=category,
        search=search,
        content_language=content_language,
        adult_content=adult_content,
        sort_by=sort_by,
        sort_order=sort_order,
        offset=offset,
        limit=limit,
        ignored=True,
    )
    response_items = [ModRead.model_validate(item).model_dump() for item in displays]
    return ModList(items=response_items, total=total)


@router.get("/recommendations", response_model=ModList)
def list_recommended_mods(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    limit: int = Query(default=5, ge=1, le=20),
):
    """Return mods associated with the user's stored preference profile."""
    mod_service = ModService(session)
    displays, total, language, missing_ids = mod_service.list_recommended_mod_displays(limit=limit)
    if missing_ids and mod_service.translation_enabled():
        background_tasks.add_task(run_missing_summaries_job, missing_ids, language)

    response_items = [ModRead.model_validate(item).model_dump() for item in displays]
    return ModList(items=response_items, total=total)


@router.get("/{mod_id}", response_model=ModRead)
def get_mod(
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
    job = create_job_run(
        session,
        "llm_regenerate_summary",
        metadata={"mod_id": mod_id, "language": language, "summary_type": "brief"},
    )

    async def handler() -> dict:
        """Run single summary regeneration in a fresh job session."""
        with Session(engine) as job_session:
            return await generate_single_summary_payload_locked(
                job_session,
                mod_id=mod_id,
                language=language,
                summary_type="brief",
            )

    enqueue_job_run(int(job.id), handler)
    return {"status": "queued", "job_id": job.id, "mod_id": mod_id, "language": language}


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
def ignore_mod(
    mod_id: int,
    session: SessionDep,
):
    """Mark a mod as ignored."""
    if not ModService(session).mark_mod_ignored(mod_id):
        raise HTTPException(status_code=404, detail="Mod not found")
    return {"ignored": True}


@router.post("/{mod_id}/unignore")
def unignore_mod(
    mod_id: int,
    session: SessionDep,
):
    """Restore an ignored mod to the visible mod list."""
    if not ModService(session).mark_mod_visible(mod_id):
        raise HTTPException(status_code=404, detail="Mod not found")
    return {"ignored": False}

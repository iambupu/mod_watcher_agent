# 中文注释：装配 FastAPI 应用、中间件、静态资源和 API 路由。

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.api import (
    routes_agent,
    routes_auth,
    routes_favorites,
    routes_jobs,
    routes_logs,
    routes_loverslab_browser,
    routes_mods,
    routes_notifications,
    routes_rules,
    routes_settings,
    routes_system_notifications,
    routes_updates,
)
from app.config import settings
from app.db import engine, init_db
from app.jobs.scheduler import setup_scheduler
from app.jobs.tracked_jobs import mark_interrupted_jobs_failed
from app.logger import setup_logging
from app.runtime_paths import build_runtime_paths, is_frozen
from app.security import AccessPolicy, require_safe_bind_host
from app.services.settings_service import SettingsService
from app.utils.boolean import parse_bool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize runtime services and shut down the scheduler on app exit."""
    _app.state.database_ready = False
    try:
        require_safe_bind_host()
        setup_logging()
        init_db()
        _app.state.database_ready = True
        with Session(engine) as session:
            SettingsService(session).init_defaults()
            interrupted_count = mark_interrupted_jobs_failed(session)
            if interrupted_count:
                logger.warning("Marked %s interrupted job runs as failed", interrupted_count)
            try:
                await setup_scheduler(session)
                logger.info("Scheduler started successfully")
            except Exception as e:
                logger.error("Failed to start scheduler: %s", e)
        yield
    finally:
        from app.jobs.scheduler import scheduler

        try:
            if scheduler.running:
                scheduler.shutdown(wait=False)
        except Exception:
            logger.exception("Failed to stop the scheduler")

        try:
            await routes_loverslab_browser.fetcher.close_login()
        except Exception:
            logger.exception("Failed to close the persistent browser")
        _app.state.database_ready = False


app = FastAPI(
    title="Mod Watcher Agent",
    version="0.3.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.MW_ALLOWED_ORIGINS or settings.CORS_ORIGINS,
    allow_origin_regex=settings.MW_ALLOWED_ORIGIN_REGEX or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def local_only_api_guard(request: Request, call_next):
    """Apply the configured local/LAN access policy before route handlers run."""
    policy = AccessPolicy()
    decision = policy.evaluate(request)
    if not decision.allow:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=decision.status_code,
            content={"detail": decision.detail},
        )
    response = await call_next(request)
    if decision.set_cookie:
        response.set_cookie(
            key="mw_session",
            value=decision.set_cookie,
            httponly=True,
            samesite="strict",
            max_age=86400 * 30,
            path="/",
        )
    return response


app.include_router(routes_auth.router)
app.include_router(routes_mods.router)
app.include_router(routes_agent.router)
app.include_router(routes_rules.router)
app.include_router(routes_favorites.router)
app.include_router(routes_updates.router)
app.include_router(routes_settings.router)
app.include_router(routes_jobs.router)
app.include_router(routes_logs.router)
app.include_router(routes_notifications.router)
app.include_router(routes_system_notifications.router)
app.include_router(routes_loverslab_browser.router)


FRONTEND_DIST_DIR = build_runtime_paths().frontend_dist_dir


@app.get("/api/health")
async def health() -> dict[str, object]:
    """Report backend readiness for the desktop bootstrapper and diagnostics."""
    from app.jobs.scheduler import scheduler

    return {
        "status": "ok",
        "version": app.version,
        "database": "ready" if getattr(app.state, "database_ready", False) else "starting",
        "scheduler": "running" if scheduler.running else "stopped",
        "frontend": "ready" if FRONTEND_DIST_DIR.joinpath("index.html").is_file() else "missing",
        "desktop": parse_bool(os.getenv("MW_DESKTOP_MODE"), default=False),
        "packaged": is_frozen(),
    }


if FRONTEND_DIST_DIR.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST_DIR / "assets")),
        name="frontend-assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        """Serve built frontend files and fall back to the SPA entrypoint."""
        requested_path = (FRONTEND_DIST_DIR / full_path).resolve()
        try:
            requested_path.relative_to(FRONTEND_DIST_DIR.resolve())
        except ValueError:
            requested_path = FRONTEND_DIST_DIR / "index.html"

        if requested_path.is_file():
            return FileResponse(requested_path)
        return FileResponse(FRONTEND_DIST_DIR / "index.html")
else:
    @app.get("/")
    async def root():
        return {"service": "Mod Watcher Agent", "version": "0.3.1"}

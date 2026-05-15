import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from app.db import init_db, engine
from app.config import settings
from app.api import (
    routes_mods,
    routes_rules,
    routes_favorites,
    routes_updates,
    routes_settings,
    routes_jobs,
    routes_logs,
    routes_system_notifications,
)
from app.jobs.scheduler import setup_scheduler
from app.services.settings_service import SettingsService
from app.logger import setup_logging
from app.security import is_local_request

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    with Session(engine) as session:
        SettingsService(session).init_defaults()
        try:
            await setup_scheduler(session)
            logger.info("Scheduler started successfully")
        except Exception as e:
            logger.error("Failed to start scheduler: %s", e)
    yield
    from app.jobs.scheduler import scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Mod Watcher Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def local_only_api_guard(request: Request, call_next):
    if settings.LOCAL_ONLY_API and request.url.path.startswith("/api/"):
        if not is_local_request(request):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=403,
                content={"detail": "Remote API access is disabled on this instance"},
            )
    return await call_next(request)


app.include_router(routes_mods.router)
app.include_router(routes_rules.router)
app.include_router(routes_favorites.router)
app.include_router(routes_updates.router)
app.include_router(routes_settings.router)
app.include_router(routes_jobs.router)
app.include_router(routes_logs.router)
app.include_router(routes_system_notifications.router)


@app.get("/")
async def root():
    return {"service": "Mod Watcher Agent", "version": "0.1.0"}

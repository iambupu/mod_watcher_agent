import io
import json
import platform
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.jobs.scheduler import register_jobs
from app.schemas.settings import SettingsRead, SettingsUpdate
from app.services.llm_client import create_llm_client
from app.services.llm_provider_test_service import test_llm_providers as run_llm_provider_tests
from app.services.notification_service import NotificationService
from app.services.settings_payload_service import (
    EXPORT_EXCLUDED_PREFIXES,
    SettingsPayloadError,
    prepare_settings_update,
    redact_settings_for_response,
    sanitize_export_settings,
    settings_import_items,
)
from app.services.settings_service import SettingsService
from app.services.windows_autostart_service import AutoStartUnsupportedError, set_windows_auto_start

router = APIRouter(prefix="/api/settings", tags=["settings"])


class AutoStartRequest(BaseModel):
    enabled: bool = False


SessionDep = Annotated[Session, Depends(get_session)]


def _raise_settings_error(exc: SettingsPayloadError | AutoStartUnsupportedError) -> None:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("", response_model=SettingsRead)
def get_settings(
    session: SessionDep,
):
    """读取并返回对应的数据。"""
    service = SettingsService(session)
    db_settings = service.get_all(exclude_prefixes=EXPORT_EXCLUDED_PREFIXES)
    merged = dict(service.DEFAULTS)
    merged.update(db_settings)
    return SettingsRead(settings=redact_settings_for_response(merged))


@router.put("", response_model=SettingsRead)
def update_settings(
    data: SettingsUpdate,
    session: SessionDep,
):
    """更新已有数据并返回结果。"""
    service = SettingsService(session)
    items = {key: value for key, value in data.settings.items() if value is not None}
    if items:
        try:
            service.set_batch(prepare_settings_update(service, items))
        except SettingsPayloadError as exc:
            _raise_settings_error(exc)
        register_jobs(session)

    db_settings = service.get_all(exclude_prefixes=EXPORT_EXCLUDED_PREFIXES)
    merged = dict(service.DEFAULTS)
    merged.update(db_settings)
    return SettingsRead(settings=redact_settings_for_response(merged))


@router.post("/telegram/test")
async def test_telegram(
    session: SessionDep,
):
    """处理当前模块的业务逻辑并返回结果。"""
    notifier = NotificationService(session)
    ok = await notifier.send_telegram_message("Mod Watcher Agent 测试消息")
    return {"success": ok, "message": "Telegram test sent" if ok else "Failed or not configured"}


@router.post("/discord/test")
async def test_discord(
    session: SessionDep,
):
    """处理当前模块的业务逻辑并返回结果。"""
    notifier = NotificationService(session)
    ok = await notifier.send_discord_webhook("Mod Watcher Agent 测试消息")
    return {"success": ok, "message": "Discord test sent" if ok else "Failed or not configured"}


@router.post("/llm/test")
async def test_llm_providers(
    session: SessionDep,
    body: Annotated[dict[str, Any] | None, Body()] = None,
):
    """处理当前模块的业务逻辑并返回结果。"""
    return await run_llm_provider_tests(SettingsService(session), body, create_client=create_llm_client)


@router.post("/export")
def export_settings(
    session: SessionDep,
):
    """处理当前模块的业务逻辑并返回结果。"""
    svc = SettingsService(session)
    raw = svc.get_all(exclude_prefixes=EXPORT_EXCLUDED_PREFIXES)
    data = sanitize_export_settings(raw)
    json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=mod_watcher_settings.json"},
    )


@router.post("/import")
def import_settings(
    data: dict[str, Any],
    session: SessionDep,
):
    """处理当前模块的业务逻辑并返回结果。"""
    svc = SettingsService(session)
    items = settings_import_items(data)
    if items:
        try:
            svc.set_batch(prepare_settings_update(svc, items))
        except SettingsPayloadError as exc:
            _raise_settings_error(exc)
        register_jobs(session)
    return {"imported": len(items)}


@router.post("/auto-start")
def set_auto_start(
    data: Annotated[AutoStartRequest, Body()],
    session: SessionDep,
):
    """处理当前模块的业务逻辑并返回结果。"""
    try:
        result = set_windows_auto_start(data.enabled, platform_module=platform)
    except AutoStartUnsupportedError as exc:
        _raise_settings_error(exc)
    if result.get("success"):
        SettingsService(session).set("auto_start", str(data.enabled).lower())
    return result

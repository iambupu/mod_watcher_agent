import io
import json
import platform
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.runtime_paths import build_runtime_paths
from app.schemas.settings import SettingsRead, SettingsUpdate
from app.services.llm_client import create_llm_client
from app.services.llm_provider_test_service import test_llm_providers as run_llm_provider_tests
from app.services.log_directory_service import LogDirectoryOpenError, open_directory_in_system
from app.services.notification_service import NotificationService
from app.services.settings_payload_service import (
    EXPORT_EXCLUDED_PREFIXES,
    SettingsPayloadError,
    redact_settings_for_response,
    sanitize_export_settings,
)
from app.services.settings_service import SettingsService
from app.services.settings_update_service import apply_settings_update, import_settings_payload
from app.services.windows_autostart_service import AutoStartUnsupportedError, set_windows_auto_start

router = APIRouter(prefix="/api/settings", tags=["settings"])


class AutoStartRequest(BaseModel):
    enabled: bool = False


class RuntimePathsRead(BaseModel):
    config_dir: str
    default_database_path: str
    active_database_path: str


SessionDep = Annotated[Session, Depends(get_session)]


def _merged_settings(service: SettingsService) -> dict[str, str]:
    db_settings = service.get_all(exclude_prefixes=EXPORT_EXCLUDED_PREFIXES)
    merged = dict(service.DEFAULTS)
    merged.update(db_settings)
    merged["database_path"] = str(build_runtime_paths().database_path)
    return merged


def _raise_settings_error(exc: SettingsPayloadError | AutoStartUnsupportedError) -> None:
    """把设置服务层异常转换为 FastAPI HTTPException。"""
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("", response_model=SettingsRead)
def get_settings(
    session: SessionDep,
):
    """读取设置，并对敏感字段做响应脱敏。"""
    service = SettingsService(session)
    return SettingsRead(settings=redact_settings_for_response(_merged_settings(service)))


@router.put("", response_model=SettingsRead)
def update_settings(
    data: SettingsUpdate,
    session: SessionDep,
):
    """更新设置项，返回合并默认值后的脱敏配置。"""
    service = SettingsService(session)
    items = {key: value for key, value in data.settings.items() if value is not None}
    if items:
        try:
            service = apply_settings_update(session, items)
        except SettingsPayloadError as exc:
            _raise_settings_error(exc)

    return SettingsRead(settings=redact_settings_for_response(_merged_settings(service)))


@router.get("/runtime-paths", response_model=RuntimePathsRead)
def get_runtime_paths():
    """返回设置页需要展示的只读运行时路径。"""
    paths = build_runtime_paths()
    return RuntimePathsRead(
        config_dir=str(paths.config_dir),
        default_database_path=str(paths.default_database_path),
        active_database_path=str(paths.database_path),
    )


@router.post("/open-config-dir")
def open_config_directory():
    """调用系统文件管理器打开应用配置目录。"""
    paths = build_runtime_paths()
    try:
        config_dir = open_directory_in_system(paths.config_dir)
    except LogDirectoryOpenError as exc:
        status_code = 501 if exc.unsupported else 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"opened": True, "path": str(config_dir)}


@router.post("/telegram/test")
async def test_telegram(
    session: SessionDep,
):
    """向当前 Telegram 配置发送一条测试消息。"""
    notifier = NotificationService(session)
    ok = await notifier.send_telegram_message("Mod Watcher Agent 测试消息")
    return {"success": ok, "message": "Telegram test sent" if ok else "Failed or not configured"}


@router.post("/discord/test")
async def test_discord(
    session: SessionDep,
):
    """向当前 Discord Webhook 配置发送一条测试消息。"""
    notifier = NotificationService(session)
    ok = await notifier.send_discord_webhook("Mod Watcher Agent 测试消息")
    return {"success": ok, "message": "Discord test sent" if ok else "Failed or not configured"}


@router.post("/llm/test")
async def test_llm_providers(
    session: SessionDep,
    body: Annotated[dict[str, Any] | None, Body()] = None,
):
    """测试 LLM 供应商链或请求体里的临时供应商配置。"""
    return await run_llm_provider_tests(SettingsService(session), body, create_client=create_llm_client)


@router.post("/export")
def export_settings(
    session: SessionDep,
):
    """导出可迁移设置，并排除密钥、运行态等敏感前缀。"""
    svc = SettingsService(session)
    raw = svc.get_all(exclude_prefixes=EXPORT_EXCLUDED_PREFIXES)
    raw["database_path"] = str(build_runtime_paths().database_path)
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
    """导入设置负载，服务层负责校验和归一化。"""
    try:
        imported = import_settings_payload(session, data)
    except SettingsPayloadError as exc:
        _raise_settings_error(exc)
    return {"imported": imported}


@router.post("/auto-start")
def set_auto_start(
    data: Annotated[AutoStartRequest, Body()],
    session: SessionDep,
):
    """切换 Windows 开机自启，并把成功状态写回设置。"""
    try:
        result = set_windows_auto_start(data.enabled, platform_module=platform)
    except AutoStartUnsupportedError as exc:
        _raise_settings_error(exc)
    if result.get("success"):
        SettingsService(session).set("auto_start", str(data.enabled).lower())
    return result

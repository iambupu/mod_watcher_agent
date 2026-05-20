import io
import json
import platform
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.config import settings
from app.db import get_session
from app.jobs.scheduler import register_jobs
from app.schemas.settings import SettingsRead, SettingsUpdate
from app.security import validate_outbound_url
from app.services.llm_client import DEFAULT_MODELS, create_llm_client
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])

SENSITIVE_KEYS = {
    "nexus_api_key",
    "openai_api_key",
    "llm_api_key",
    "telegram_bot_token",
    "telegram_chat_id",
    "discord_webhook_url",
    "proxy_password",
}
MASKED_VALUE = "********"
EXPORT_EXCLUDED_PREFIXES = ("agent_chat_",)
NUMERIC_SETTING_BOUNDS: dict[str, tuple[int, int]] = {
    "summary_report_interval_minutes": (0, 10080),
    "watchdog_check_interval_minutes": (1, 180),
    "watchdog_grace_minutes": (1, 1440),
    "watchdog_max_catchup_per_run": (1, 20),
}
MIN_LENGTH_SENSITIVE_KEYS: dict[str, int] = {
    "nexus_api_key": 8,
    "openai_api_key": 8,
    "llm_api_key": 8,
    "telegram_bot_token": 20,
}
ACCESS_PROFILES_REQUIRING_TOKEN = {"local_strict", "shared_lan"}
ACCESS_PROFILES = {"local_relaxed", "local_strict", "shared_lan"}


SessionDep = Annotated[Session, Depends(get_session)]


class AutoStartRequest(BaseModel):
    enabled: bool = False


def _mask_if_present(value: str) -> str:
    return MASKED_VALUE if value.strip() else ""


def _redact_settings_for_response(settings: dict[str, str]) -> dict[str, str]:
    redacted = dict(settings)
    for key in SENSITIVE_KEYS:
        if key in redacted:
            redacted[key] = _mask_if_present(redacted.get(key, ""))

    raw_providers = redacted.get("llm_providers_json")
    if raw_providers:
        try:
            providers = json.loads(raw_providers)
            if isinstance(providers, list):
                for provider in providers:
                    if isinstance(provider, dict) and "api_key" in provider:
                        provider["api_key"] = _mask_if_present(str(provider.get("api_key") or ""))
                redacted["llm_providers_json"] = json.dumps(providers, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    return redacted


def _merge_provider_keys(
    incoming_json: str,
    existing_json: str | None,
) -> str:
    try:
        incoming = json.loads(incoming_json)
    except json.JSONDecodeError:
        return incoming_json
    if not isinstance(incoming, list):
        return incoming_json

    existing_map: dict[str, str] = {}
    if existing_json:
        try:
            existing = json.loads(existing_json)
            if isinstance(existing, list):
                for item in existing:
                    if isinstance(item, dict):
                        provider = str(item.get("provider") or "")
                        if provider:
                            existing_map[provider] = str(item.get("api_key") or "")
        except json.JSONDecodeError:
            pass

    changed = False
    for item in incoming:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "")
        api_key = str(item.get("api_key") or "")
        if api_key == MASKED_VALUE:
            item["api_key"] = existing_map.get(provider, "")
            changed = True

    if not changed:
        return incoming_json
    return json.dumps(incoming, ensure_ascii=False)


def _restore_masked_provider_api_keys(
    providers: list[dict],
    existing_json: str | None,
) -> list[dict]:
    existing_map: dict[str, str] = {}
    if existing_json:
        try:
            existing = json.loads(existing_json)
            if isinstance(existing, list):
                for item in existing:
                    if isinstance(item, dict):
                        provider = str(item.get("provider") or "")
                        if provider:
                            existing_map[provider] = str(item.get("api_key") or "")
        except json.JSONDecodeError:
            pass

    restored: list[dict] = []
    for item in providers:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        provider = str(copied.get("provider") or "")
        api_key = str(copied.get("api_key") or "")
        if api_key == MASKED_VALUE:
            copied["api_key"] = existing_map.get(provider, "")
        restored.append(copied)
    return restored


def _prepare_settings_update(
    service: SettingsService,
    items: dict[str, str],
) -> dict[str, str]:
    sanitized = dict(items)
    access_profile = sanitized.get("access_profile")
    if access_profile is not None:
        profile = str(access_profile).strip().lower()
        if profile not in ACCESS_PROFILES:
            raise HTTPException(status_code=422, detail="access_profile is invalid")
        if profile in ACCESS_PROFILES_REQUIRING_TOKEN and not settings.MW_ADMIN_TOKEN:
            raise HTTPException(
                status_code=422,
                detail="MW_ADMIN_TOKEN must be configured before enabling token-required access profiles",
            )
        sanitized["access_profile"] = profile
    for key in SENSITIVE_KEYS:
        value = sanitized.get(key)
        if value == MASKED_VALUE:
            sanitized.pop(key, None)
    for key, min_len in MIN_LENGTH_SENSITIVE_KEYS.items():
        raw = sanitized.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        if len(value) < min_len:
            raise HTTPException(status_code=422, detail=f"{key} is too short")
    webhook = sanitized.get("discord_webhook_url")
    if webhook is not None:
        webhook_value = str(webhook).strip()
        if webhook_value and not webhook_value.startswith("https://"):
            raise HTTPException(status_code=422, detail="discord_webhook_url must start with https://")

    if "llm_providers_json" in sanitized:
        try:
            providers = json.loads(sanitized["llm_providers_json"])
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="llm_providers_json must be valid JSON") from None
        if isinstance(providers, list):
            for provider in providers:
                if not isinstance(provider, dict):
                    continue
                enabled = bool(provider.get("enabled"))
                provider_name = str(provider.get("provider") or "").strip().lower()
                api_key = str(provider.get("api_key") or "").strip()
                if enabled and provider_name != "ollama" and api_key and len(api_key) < 8:
                    raise HTTPException(status_code=422, detail=f"llm provider '{provider_name}' api_key is too short")
                if enabled:
                    validate_outbound_url(provider_name, str(provider.get("base_url") or ""))
        sanitized["llm_providers_json"] = _merge_provider_keys(
            sanitized["llm_providers_json"],
            service.get("llm_providers_json"),
        )
    for key, (min_v, max_v) in NUMERIC_SETTING_BOUNDS.items():
        raw = sanitized.get(key)
        if raw is None:
            continue
        try:
            value = int(str(raw).strip())
        except ValueError:
            raise HTTPException(status_code=422, detail=f"{key} must be an integer") from None
        if value < min_v or value > max_v:
            raise HTTPException(status_code=422, detail=f"{key} must be between {min_v} and {max_v}")
        sanitized[key] = str(value)
    return sanitized


def _sanitize_export_settings(raw: dict[str, str]) -> dict[str, str]:
    export_data: dict[str, str] = {}
    for key, value in raw.items():
        if key in SENSITIVE_KEYS:
            continue
        export_data[key] = value
    if "llm_providers_json" in export_data:
        try:
            providers = json.loads(export_data["llm_providers_json"])
            if isinstance(providers, list):
                for provider in providers:
                    if isinstance(provider, dict):
                        provider.pop("api_key", None)
                export_data["llm_providers_json"] = json.dumps(providers, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    return export_data


async def _test_llm_provider(provider_config: dict) -> dict:
    provider = str(provider_config.get("provider") or "openai")
    api_key = str(provider_config.get("api_key") or "")
    base_url = validate_outbound_url(provider, str(provider_config.get("base_url") or ""))
    model = str(provider_config.get("model") or "") or DEFAULT_MODELS.get(provider, "gpt-4o-mini")
    if not api_key and provider != "ollama":
        return {
            "provider": provider,
            "success": False,
            "latency_ms": None,
            "message": "API key is empty",
        }
    started = time.perf_counter()
    client = create_llm_client(provider, api_key, base_url)
    content = await client.chat(
        "Reply with exactly: ok",
        model,
        max_tokens=64,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)
    error = getattr(client, "last_error", "")
    detail = getattr(client, "last_detail", "")
    message = "ok"
    if not content:
        message = error or detail or "Empty response"
    elif content.strip().lower() != "ok":
        message = f"Connected; response was {content[:120]!r}"
    return {
        "provider": provider,
        "success": bool(content),
        "latency_ms": latency_ms,
        "message": message,
    }


@router.get("", response_model=SettingsRead)
def get_settings(
    session: SessionDep,
):
    service = SettingsService(session)
    db_settings = service.get_all(exclude_prefixes=EXPORT_EXCLUDED_PREFIXES)

    merged = dict(service.DEFAULTS)
    merged.update(db_settings)

    return SettingsRead(settings=_redact_settings_for_response(merged))


@router.put("", response_model=SettingsRead)
def update_settings(
    data: SettingsUpdate,
    session: SessionDep,
):
    service = SettingsService(session)
    items = {k: v for k, v in data.settings.items() if v is not None}
    if items:
        service.set_batch(_prepare_settings_update(service, items))
        register_jobs(session)

    db_settings = service.get_all(exclude_prefixes=EXPORT_EXCLUDED_PREFIXES)
    merged = dict(service.DEFAULTS)
    merged.update(db_settings)

    return SettingsRead(settings=_redact_settings_for_response(merged))


@router.post("/telegram/test")
async def test_telegram(
    session: SessionDep,
):
    notifier = NotificationService(session)
    ok = await notifier.send_telegram_message("Mod Watcher Agent 测试消息")
    return {"success": ok, "message": "Telegram test sent" if ok else "Failed or not configured"}


@router.post("/discord/test")
async def test_discord(
    session: SessionDep,
):
    notifier = NotificationService(session)
    ok = await notifier.send_discord_webhook("Mod Watcher Agent 测试消息")
    return {"success": ok, "message": "Discord test sent" if ok else "Failed or not configured"}


@router.post("/llm/test")
async def test_llm_providers(
    session: SessionDep,
    body: Annotated[dict[str, Any] | None, Body()] = None,
):
    svc = SettingsService(session)
    body = body or {}
    providers = body.get("providers")
    if not isinstance(providers, list):
        try:
            providers = json.loads(svc.get("llm_providers_json") or "[]")
        except json.JSONDecodeError:
            providers = []
    providers = _restore_masked_provider_api_keys(providers, svc.get("llm_providers_json"))
    enabled = [p for p in providers if isinstance(p, dict) and p.get("enabled")]
    enabled.sort(key=lambda p: int(p.get("priority") or 999))
    results = []
    for provider in enabled:
        results.append(await _test_llm_provider(provider))
    return {"results": results}


@router.post("/export")
def export_settings(
    session: SessionDep,
):
    svc = SettingsService(session)
    raw = svc.get_all(exclude_prefixes=EXPORT_EXCLUDED_PREFIXES)
    data = _sanitize_export_settings(raw)
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
    svc = SettingsService(session)
    items: dict[str, str] = {}
    for key, value in data.items():
        if key in SENSITIVE_KEYS:
            continue
        if (
            isinstance(value, str)
            and value.strip()
        ):
            items[key] = value
    if items:
        svc.set_batch(_prepare_settings_update(svc, items))
        register_jobs(session)
    return {"imported": len(items)}


@router.post("/auto-start")
def set_auto_start(
    data: Annotated[AutoStartRequest, Body()],
    session: SessionDep,
):
    if platform.system().lower() != "windows":
        raise HTTPException(status_code=501, detail="/api/settings/auto-start is only supported on Windows")

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

    import winreg

    root = Path(__file__).resolve().parent.parent.parent.parent
    launcher = root / "start.ps1"

    try:
        if data.enabled:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, "ModWatcherAgent", 0, winreg.REG_SZ, f'powershell.exe -WindowStyle Hidden -File "{launcher}" -Tray')
            winreg.CloseKey(key)
        else:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(key, "ModWatcherAgent")
                winreg.CloseKey(key)
            except FileNotFoundError:
                pass
        SettingsService(session).set("auto_start", str(data.enabled).lower())
        return {"success": True, "enabled": data.enabled}
    except Exception as e:
        return {"success": False, "error": str(e)}

import json
from typing import Any

from app.config import settings
from app.security import validate_outbound_url
from app.services.settings_service import SettingsService

SENSITIVE_KEYS = {
    "nexus_api_key",
    "google_search_api_key",
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
    "google_search_api_key": 8,
    "openai_api_key": 8,
    "llm_api_key": 8,
    "telegram_bot_token": 20,
}
ACCESS_PROFILES_REQUIRING_TOKEN = {"local_strict", "shared_lan"}
ACCESS_PROFILES = {"local_relaxed", "local_strict", "shared_lan"}
LOVERSLAB_SEARCH_SCRAPE_ENGINES = {"duckduckgo", "google"}


class SettingsPayloadError(Exception):
    def __init__(self, status_code: int, detail: str):
        """初始化实例并保存运行所需的依赖。"""
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def mask_if_present(value: str) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    return MASKED_VALUE if value.strip() else ""


def redact_settings_for_response(settings_data: dict[str, str]) -> dict[str, str]:
    """处理当前模块的业务逻辑并返回结果。"""
    redacted = dict(settings_data)
    for key in SENSITIVE_KEYS:
        if key in redacted:
            redacted[key] = mask_if_present(redacted.get(key, ""))

    raw_providers = redacted.get("llm_providers_json")
    if raw_providers:
        try:
            providers = json.loads(raw_providers)
            if isinstance(providers, list):
                for provider in providers:
                    if isinstance(provider, dict) and "api_key" in provider:
                        provider["api_key"] = mask_if_present(str(provider.get("api_key") or ""))
                redacted["llm_providers_json"] = json.dumps(providers, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    return redacted


def provider_key_map(existing_json: str | None) -> dict[str, str]:
    """处理当前模块的业务逻辑并返回结果。"""
    if not existing_json:
        return {}
    try:
        providers = json.loads(existing_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(providers, list):
        return {}
    keys: dict[str, str] = {}
    for item in providers:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "")
        if provider:
            keys[provider] = str(item.get("api_key") or "")
    return keys


def replace_masked_provider_keys(
    providers: list[dict],
    existing_json: str | None,
) -> tuple[list[dict], bool]:
    """处理当前模块的业务逻辑并返回结果。"""
    existing_map = provider_key_map(existing_json)
    restored: list[dict] = []
    changed = False
    for item in providers:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        provider = str(copied.get("provider") or "")
        api_key = str(copied.get("api_key") or "")
        if api_key == MASKED_VALUE:
            copied["api_key"] = existing_map.get(provider, "")
            changed = True
        restored.append(copied)
    return restored, changed


def merge_provider_keys(
    incoming_json: str,
    existing_json: str | None,
) -> str:
    """合并多个来源的数据并保持稳定顺序。"""
    try:
        incoming = json.loads(incoming_json)
    except json.JSONDecodeError:
        return incoming_json
    if not isinstance(incoming, list):
        return incoming_json

    incoming, changed = replace_masked_provider_keys(incoming, existing_json)
    if not changed:
        return incoming_json
    return json.dumps(incoming, ensure_ascii=False)


def restore_masked_provider_api_keys(
    providers: list[dict],
    existing_json: str | None,
) -> list[dict]:
    """处理当前模块的业务逻辑并返回结果。"""
    restored, _ = replace_masked_provider_keys(providers, existing_json)
    return restored


def prepare_settings_update(
    service: SettingsService,
    items: dict[str, str],
) -> dict[str, str]:
    """处理当前模块的业务逻辑并返回结果。"""
    sanitized = dict(items)
    access_profile = sanitized.get("access_profile")
    if access_profile is not None:
        profile = str(access_profile).strip().lower()
        if profile not in ACCESS_PROFILES:
            raise SettingsPayloadError(422, "access_profile is invalid")
        if profile in ACCESS_PROFILES_REQUIRING_TOKEN and not settings.MW_ADMIN_TOKEN:
            raise SettingsPayloadError(
                422,
                "MW_ADMIN_TOKEN must be configured before enabling token-required access profiles",
            )
        sanitized["access_profile"] = profile

    scrape_engine = sanitized.get("loverslab_search_scrape_engine")
    if scrape_engine is not None:
        engine = str(scrape_engine).strip().lower()
        if engine not in LOVERSLAB_SEARCH_SCRAPE_ENGINES:
            raise SettingsPayloadError(422, "loverslab_search_scrape_engine is invalid")
        sanitized["loverslab_search_scrape_engine"] = engine

    for key in SENSITIVE_KEYS:
        value = sanitized.get(key)
        if value == MASKED_VALUE:
            sanitized.pop(key, None)
    for key, min_len in MIN_LENGTH_SENSITIVE_KEYS.items():
        raw = sanitized.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if value and len(value) < min_len:
            raise SettingsPayloadError(422, f"{key} is too short")

    webhook = sanitized.get("discord_webhook_url")
    if webhook is not None:
        webhook_value = str(webhook).strip()
        if webhook_value and not webhook_value.startswith("https://"):
            raise SettingsPayloadError(422, "discord_webhook_url must start with https://")

    if "llm_providers_json" in sanitized:
        try:
            providers = json.loads(sanitized["llm_providers_json"])
        except json.JSONDecodeError:
            raise SettingsPayloadError(422, "llm_providers_json must be valid JSON") from None
        if isinstance(providers, list):
            for provider in providers:
                if not isinstance(provider, dict):
                    continue
                enabled = bool(provider.get("enabled"))
                provider_name = str(provider.get("provider") or "").strip().lower()
                api_key = str(provider.get("api_key") or "").strip()
                if enabled and provider_name != "ollama" and api_key and len(api_key) < 8:
                    raise SettingsPayloadError(422, f"llm provider '{provider_name}' api_key is too short")
                if enabled:
                    validate_outbound_url(provider_name, str(provider.get("base_url") or ""))
        sanitized["llm_providers_json"] = merge_provider_keys(
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
            raise SettingsPayloadError(422, f"{key} must be an integer") from None
        if value < min_v or value > max_v:
            raise SettingsPayloadError(422, f"{key} must be between {min_v} and {max_v}")
        sanitized[key] = str(value)
    return sanitized


def sanitize_export_settings(raw: dict[str, str]) -> dict[str, str]:
    """处理当前模块的业务逻辑并返回结果。"""
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


def settings_import_items(data: dict[str, Any]) -> dict[str, str]:
    """处理当前模块的业务逻辑并返回结果。"""
    items: dict[str, str] = {}
    for key, value in data.items():
        if key in SENSITIVE_KEYS:
            continue
        if isinstance(value, str) and value.strip():
            items[key] = value
    return items

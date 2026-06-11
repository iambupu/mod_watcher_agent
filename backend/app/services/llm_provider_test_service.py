import time
from typing import Any

from app.security import validate_outbound_url
from app.services.llm_client import create_llm_client
from app.services.llm_provider_config import (
    SUPPORTED_PROVIDERS,
    provider_config_has_credentials,
    provider_priority,
    resolve_provider_config,
)
from app.services.settings_payload_service import restore_masked_provider_api_keys
from app.services.settings_service import SettingsService
from app.utils.boolean import parse_bool
from app.utils.json import json_array


async def test_llm_provider(provider_config: dict, *, create_client=create_llm_client) -> dict:
    """向单个 LLM provider 发送最小探活请求并返回延迟和错误信息。"""
    provider, api_key, raw_base_url, model = resolve_provider_config(provider_config)
    base_url = validate_outbound_url(provider, raw_base_url)
    if not provider_config_has_credentials(provider_config):
        return {
            "provider": provider,
            "success": False,
            "latency_ms": None,
            "message": "API key is empty",
        }

    started = time.perf_counter()
    client = create_client(provider, api_key, base_url)
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


async def test_llm_providers(
    service: SettingsService,
    body: dict[str, Any] | None = None,
    *,
    create_client=create_llm_client,
) -> dict:
    """按优先级测试所有启用的 LLM provider。"""
    body = body or {}
    providers = body.get("providers")
    if not isinstance(providers, list):
        providers = json_array(service.get("llm_providers_json"))
    providers = restore_masked_provider_api_keys(providers, service.get("llm_providers_json"))
    enabled = [
        provider
        for provider in providers
        if isinstance(provider, dict)
        and parse_bool(provider.get("enabled"))
        and str(provider.get("provider") or "").strip().lower() in SUPPORTED_PROVIDERS
    ]
    enabled.sort(key=provider_priority)
    return {"results": [await test_llm_provider(provider, create_client=create_client) for provider in enabled]}

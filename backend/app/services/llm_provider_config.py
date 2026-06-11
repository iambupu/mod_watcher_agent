import os
from typing import TYPE_CHECKING, Any

from app.utils.boolean import parse_bool
from app.utils.json import json_array

if TYPE_CHECKING:
    from app.services.settings_service import SettingsService


PROVIDER_DEFINITIONS: list[dict[str, str]] = [
    {
        "provider": "ollama",
        "label": "Ollama (Local)",
        "model": "qwen3:8b",
        "base_url": "http://localhost:11434/v1",
    },
    {
        "provider": "openai",
        "label": "OpenAI",
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
    },
    {
        "provider": "anthropic",
        "label": "Anthropic",
        "model": "claude-3-5-haiku-latest",
        "base_url": "https://api.anthropic.com/v1",
    },
    {
        "provider": "gemini",
        "label": "Google Gemini",
        "model": "gemini-2.0-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1",
    },
    {
        "provider": "groq",
        "label": "Groq",
        "model": "mixtral-8x7b-32768",
        "base_url": "https://api.groq.com/openai/v1",
    },
    {
        "provider": "deepseek",
        "label": "DeepSeek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/v1",
    },
    {
        "provider": "openrouter",
        "label": "OpenRouter",
        "model": "gpt-4o-mini",
        "base_url": "https://openrouter.ai/api/v1",
    },
    {
        "provider": "siliconflow",
        "label": "硅基流动 (SiliconFlow)",
        "model": "Qwen/Qwen3-8B",
        "base_url": "https://api.siliconflow.cn/v1",
    },
    {
        "provider": "xai",
        "label": "xAI",
        "model": "grok-4.20-reasoning",
        "base_url": "https://api.x.ai/v1",
    },
    {
        "provider": "kimi",
        "label": "Kimi",
        "model": "kimi-k2.6",
        "base_url": "https://api.moonshot.cn/v1",
    },
    {
        "provider": "qwen",
        "label": "通义千问 (Qwen)",
        "model": "qwen-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    {
        "provider": "minimax",
        "label": "MiniMax",
        "model": "MiniMax-M2.7",
        "base_url": "https://api.minimax.io/v1",
    },
]

DEFAULT_MODELS = {
    item["provider"]: item["model"]
    for item in PROVIDER_DEFINITIONS
}
DEFAULT_BASE_URLS = {
    item["provider"]: item["base_url"]
    for item in PROVIDER_DEFINITIONS
}
SUPPORTED_PROVIDERS = set(DEFAULT_MODELS)


def provider_default_model(provider: str) -> str:
    """返回 provider 的默认模型，未知 provider 回退到 OpenAI 默认。"""
    return DEFAULT_MODELS.get((provider or "").strip().lower(), "gpt-4o-mini")


def provider_default_base_url(provider: str) -> str:
    """返回 provider 的默认 base_url，未知 provider 回退到 OpenAI。"""
    return DEFAULT_BASE_URLS.get((provider or "").strip().lower(), DEFAULT_BASE_URLS["openai"])


def resolve_provider_config(provider_config: dict[str, Any]) -> tuple[str, str, str, str]:
    """把前端或设置中的 provider 配置规范化为调用参数。"""
    provider = str(provider_config.get("provider") or "openai").strip().lower()
    api_key = str(provider_config.get("api_key") or "")
    base_url = str(provider_config.get("base_url") or "")
    model = str(provider_config.get("model") or "") or provider_default_model(provider)
    return provider, api_key, base_url, model


def provider_requires_api_key(provider: str) -> bool:
    """判断 provider 是否需要 API key；本地 Ollama 例外。"""
    return (provider or "").strip().lower() != "ollama"


def provider_has_credentials(provider: str, api_key: str) -> bool:
    """判断 provider 是否具备可尝试调用的凭据。"""
    return bool((api_key or "").strip()) or not provider_requires_api_key(provider)


def provider_config_has_credentials(provider_config: dict[str, Any]) -> bool:
    """判断一条 provider 配置是否具备可用凭据。"""
    provider, api_key, _, _ = resolve_provider_config(provider_config)
    return provider_has_credentials(provider, api_key)


def default_provider_configs() -> list[dict[str, Any]]:
    """构建首次启动时的 provider 列表，并吸收环境变量默认值。"""
    default_api_key = os.getenv("LLM_API_KEY", "")
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    configs: list[dict[str, Any]] = []
    for index, item in enumerate(PROVIDER_DEFINITIONS, start=1):
        provider = item["provider"]
        provider_default_api_key = (
            openai_api_key
            if provider == "openai" and not default_api_key
            else default_api_key
        )
        configs.append(
            {
                "provider": provider,
                "enabled": provider == "ollama",
                "priority": index,
                "model": (
                    os.getenv("LLM_MODEL", "") if provider == "ollama" else ""
                ) or item["model"],
                "api_key": provider_default_api_key,
                "base_url": (
                    os.getenv("LLM_BASE_URL", "") if provider == "ollama" else ""
                ) or item["base_url"],
            }
        )
    return configs


def get_provider_chain(settings: "SettingsService") -> list[dict[str, Any]]:
    """读取启用的 provider 链，缺省时兼容旧版单 provider 设置。"""
    raw = settings.get("llm_providers_json") or ""
    providers: list[dict[str, Any]] = []
    if raw:
        providers = [
            item
            for item in json_array(raw)
            if isinstance(item, dict)
            and parse_bool(item.get("enabled"))
            and str(item.get("provider") or "").strip().lower() in SUPPORTED_PROVIDERS
        ]

    if not providers:
        providers = [
            {
                "provider": settings.get("llm_provider") or "openai",
                "model": settings.get("llm_model") or "",
                "api_key": settings.get("llm_api_key") or settings.get("openai_api_key") or "",
                "base_url": settings.get("llm_base_url") or "",
                "priority": 1,
            }
        ]

    return sorted(providers, key=provider_priority)


def provider_priority(provider_config: dict[str, Any]) -> int:
    """Return a stable fallback priority for legacy or malformed stored config."""
    try:
        return int(str(provider_config.get("priority") or "").strip())
    except ValueError:
        return 999

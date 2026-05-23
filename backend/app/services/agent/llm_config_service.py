from app.services.llm_provider_config import get_provider_chain, resolve_provider_config
from app.services.settings_service import SettingsService


def get_llm_config(
    settings: SettingsService,
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> tuple[str, str, str, str]:
    """读取并返回对应的数据。"""
    enabled = get_provider_chain(settings)
    override_provider = (provider_override or "").strip().lower()
    override_model = (model_override or "").strip()

    if override_provider:
        for item in enabled:
            provider = str(item.get("provider") or "").strip().lower()
            if provider != override_provider:
                continue
            provider, api_key, base_url, model = resolve_provider_config(item)
            model = override_model or model
            return provider, api_key, base_url, model

    if enabled:
        p = enabled[0]
        provider, api_key, base_url, model = resolve_provider_config(p)
        model = override_model or model
        return provider, api_key, base_url, model

    provider = (settings.get("llm_provider") or "openai").strip().lower()
    api_key = settings.get("llm_api_key") or settings.get("openai_api_key") or ""
    base_url = settings.get("llm_base_url") or ""
    model = override_model or resolve_provider_config({
        "provider": provider,
        "model": settings.get("llm_model") or "",
    })[3]
    return provider, api_key, base_url, model

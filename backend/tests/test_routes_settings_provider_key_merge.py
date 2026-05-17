import json

from app.api.routes_settings import MASKED_VALUE, _restore_masked_provider_api_keys


def test_restore_masked_provider_api_keys_reuses_stored_keys() -> None:
    providers = [
        {"provider": "deepseek", "enabled": True, "api_key": MASKED_VALUE},
        {"provider": "ollama", "enabled": True, "api_key": ""},
    ]
    existing = json.dumps(
        [
            {"provider": "deepseek", "api_key": "dsk-real-key"},
            {"provider": "openai", "api_key": "sk-real-key"},
        ],
        ensure_ascii=False,
    )

    restored = _restore_masked_provider_api_keys(providers, existing)

    assert restored[0]["api_key"] == "dsk-real-key"
    assert restored[1]["api_key"] == ""


def test_restore_masked_provider_api_keys_keeps_non_masked_value() -> None:
    providers = [{"provider": "deepseek", "enabled": True, "api_key": "new-key"}]
    existing = json.dumps([{"provider": "deepseek", "api_key": "old-key"}], ensure_ascii=False)

    restored = _restore_masked_provider_api_keys(providers, existing)

    assert restored[0]["api_key"] == "new-key"


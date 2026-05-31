"""Tests for SettingsService."""

import json

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.settings import Setting
from app.services.llm_provider_config import get_provider_chain
from app.services.settings_payload_service import (
    SettingsPayloadError,
    prepare_settings_update,
    settings_import_items,
)
from app.services.settings_service import SettingsService


@pytest.fixture(name="engine")
def fixture_engine():
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def fixture_session(engine):
    with Session(engine) as session:
        yield session


class TestSettingsService:
    """Tests for SettingsService CRUD and defaults."""

    @pytest.fixture
    def service(self, session):
        return SettingsService(session)

    def test_get_returns_none_for_missing_key(self, service):
        assert service.get("nonexistent") is None

    def test_set_and_get(self, service):
        service.set("game_domain", "skyrim")
        assert service.get("game_domain") == "skyrim"

    def test_set_updates_existing(self, service):
        service.set("game_domain", "skyrim")
        service.set("game_domain", "oblivion")
        assert service.get("game_domain") == "oblivion"

    def test_get_all_returns_dict(self, service):
        service.set("key1", "value1")
        service.set("key2", "value2")
        result = service.get_all()
        assert result == {"key1": "value1", "key2": "value2"}

    def test_get_all_empty(self, service):
        assert service.get_all() == {}

    def test_set_batch(self, service):
        service.set_batch({"a": "1", "b": "2", "c": "3"})
        assert service.get_all() == {"a": "1", "b": "2", "c": "3"}

    def test_init_defaults_inserts_missing(self, service):
        service.init_defaults()
        result = service.get_all()
        for key, value in service.DEFAULTS.items():
            assert result[key] == value

    def test_init_defaults_does_not_overwrite_existing(self, service):
        service.set("game_domain", "customdomain")
        service.init_defaults()
        assert service.get("game_domain") == "customdomain"
        assert service.get("adult_policy") == "include"

    def test_defaults_parse_allow_lan_with_shared_boolean_parser(self, monkeypatch, session):
        monkeypatch.setenv("MW_ALLOW_LAN", "on")
        assert SettingsService(session).DEFAULTS["allow_lan"] == "true"

        monkeypatch.setenv("MW_ALLOW_LAN", "off")
        assert SettingsService(session).DEFAULTS["allow_lan"] == "false"

    def test_default_llm_providers_include_openai_compatible_cn_and_global_providers(self, service):
        providers = json.loads(service.DEFAULTS["llm_providers_json"])
        by_name = {provider["provider"]: provider for provider in providers}
        expected = {
            "siliconflow": ("Qwen/Qwen3-8B", "https://api.siliconflow.cn/v1"),
            "xai": ("grok-4.20-reasoning", "https://api.x.ai/v1"),
            "kimi": ("kimi-k2.6", "https://api.moonshot.cn/v1"),
            "qwen": ("qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "minimax": ("MiniMax-M2.7", "https://api.minimax.io/v1"),
        }
        for name, (model, base_url) in expected.items():
            assert by_name[name]["enabled"] is False
            assert by_name[name]["model"] == model
            assert by_name[name]["base_url"] == base_url

    def test_google_search_defaults_are_available_for_loverslab_agent_tool(self, service):
        assert service.DEFAULTS["google_search_api_key"] == ""
        assert service.DEFAULTS["google_search_engine_id"] == ""
        assert service.DEFAULTS["loverslab_search_scrape_enabled"] == "true"
        assert service.DEFAULTS["loverslab_search_scrape_engine"] == "duckduckgo"

    def test_updated_at_is_set_on_insert(self, service):
        service.set("test_key", "test_value")
        row = service.session.exec(
            select(Setting).where(Setting.key == "test_key")
        ).first()
        assert row.updated_at is not None
        assert "T" in row.updated_at

    def test_updated_at_is_refreshed_on_update(self, service):
        service.set("test_key", "v1")
        old = service.session.exec(
            select(Setting).where(Setting.key == "test_key")
        ).first()
        old_updated_at = old.updated_at
        service.set("test_key", "v2")
        new = service.session.exec(
            select(Setting).where(Setting.key == "test_key")
        ).first()
        assert new.updated_at != old_updated_at


class TestDefaultsMerge:
    """Tests for defaults merge logic used in GET /api/settings."""

    @pytest.fixture(name="engine")
    def fixture_engine(self):
        engine = create_engine("sqlite://", echo=False)
        SQLModel.metadata.create_all(engine)
        yield engine
        SQLModel.metadata.drop_all(engine)

    @pytest.fixture(name="session")
    def fixture_session(self, engine):
        with Session(engine) as session:
            yield session

    def test_merge_fills_missing_with_defaults(self, session):
        service = SettingsService(session)
        service.init_defaults()
        service.set("game_domain", "customdomain")
        merged = dict(service.DEFAULTS)
        merged.update(service.get_all())
        assert merged["game_domain"] == "customdomain"
        assert merged["adult_policy"] == "include"

    def test_merge_when_db_empty_returns_all_defaults(self, session):
        service = SettingsService(session)
        merged = dict(service.DEFAULTS)
        merged.update(service.get_all())
        assert merged == service.DEFAULTS


class TestSettingsImportPayload:
    def test_import_keeps_empty_non_sensitive_values(self):
        items = settings_import_items({
            "proxy_host": "",
            "bind_host": "127.0.0.1",
        })

        assert items == {
            "proxy_host": "",
            "bind_host": "127.0.0.1",
        }

    def test_import_skips_sensitive_and_internal_values(self):
        items = settings_import_items({
            "llm_api_key": "secret",
            "agent_chat_session": "cached state",
            "summary_mode": "bilingual",
        })

        assert items == {"summary_mode": "bilingual"}

    def test_prepare_update_rejects_non_array_llm_provider_config(self, session):
        service = SettingsService(session)

        with pytest.raises(SettingsPayloadError, match="must be a JSON array"):
            prepare_settings_update(service, {"llm_providers_json": "{}"})

    def test_prepare_update_rejects_unknown_llm_provider(self, session):
        service = SettingsService(session)
        payload = json.dumps([
            {
                "provider": "unknown",
                "enabled": False,
                "priority": 1,
                "model": "",
                "api_key": "",
                "base_url": "",
            }
        ])

        with pytest.raises(SettingsPayloadError, match="unsupported"):
            prepare_settings_update(service, {"llm_providers_json": payload})

    def test_prepare_update_rejects_invalid_llm_provider_priority(self, session):
        service = SettingsService(session)
        payload = json.dumps([
            {
                "provider": "openai",
                "enabled": False,
                "priority": "last",
                "model": "",
                "api_key": "",
                "base_url": "",
            }
        ])

        with pytest.raises(SettingsPayloadError, match="priority must be an integer"):
            prepare_settings_update(service, {"llm_providers_json": payload})

    def test_prepare_update_treats_string_false_provider_as_disabled(self, session):
        service = SettingsService(session)
        payload = json.dumps([
            {
                "provider": "openai",
                "enabled": "false",
                "priority": 1,
                "model": "gpt-4o-mini",
                "api_key": "",
                "base_url": "http://169.254.169.254/v1",
            }
        ])

        result = prepare_settings_update(service, {"llm_providers_json": payload})

        assert result["llm_providers_json"] == payload

    def test_provider_chain_ignores_unknown_providers_and_tolerates_bad_priority(self, session):
        service = SettingsService(session)
        service.set(
            "llm_providers_json",
            json.dumps(
                [
                    {
                        "provider": "unknown",
                        "enabled": True,
                        "priority": 1,
                    },
                    {
                        "provider": "openai",
                        "enabled": True,
                        "priority": "last",
                        "model": "gpt-4o-mini",
                        "api_key": "valid-key",
                        "base_url": "https://api.openai.com/v1",
                    },
                ]
            ),
        )

        chain = get_provider_chain(service)

        assert [provider["provider"] for provider in chain] == ["openai"]

    def test_provider_chain_treats_string_false_as_disabled(self, session):
        service = SettingsService(session)
        service.set(
            "llm_providers_json",
            json.dumps(
                [
                    {
                        "provider": "openai",
                        "enabled": "false",
                        "priority": 1,
                        "model": "gpt-4o-mini",
                        "api_key": "valid-key",
                        "base_url": "https://api.openai.com/v1",
                    },
                    {
                        "provider": "ollama",
                        "enabled": "true",
                        "priority": 2,
                        "model": "qwen3:8b",
                        "api_key": "",
                        "base_url": "http://localhost:11434/v1",
                    },
                ]
            ),
        )

        chain = get_provider_chain(service)

        assert [provider["provider"] for provider in chain] == ["ollama"]

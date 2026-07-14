# 中文注释：说明 backend/app/tests/test_llm_provider_test_service.py 的模块职责，便于后续维护定位。

import json

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.services.llm_provider_test_service import test_llm_providers as run_llm_provider_tests
from app.services.settings_service import SettingsService


@pytest.fixture(name="session")
def fixture_session():
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class FakeClient:
    last_error = ""
    last_detail = ""

    async def chat(self, prompt: str, model: str, max_tokens: int = 64) -> str:  # noqa: ARG002
        return "ok"


def fake_client(provider: str, api_key: str, base_url: str):  # noqa: ARG001
    return FakeClient()


class FailingGeminiClient:
    last_error = "401 for https://example.test/model?key=stored-gemini-secret"
    last_detail = ""

    async def chat(self, prompt: str, model: str, max_tokens: int = 64) -> str:  # noqa: ARG002
        return ""


def failing_gemini_client(provider: str, api_key: str, base_url: str):  # noqa: ARG001
    return FailingGeminiClient()


@pytest.mark.asyncio
async def test_llm_provider_test_ignores_legacy_non_array_config(session):
    service = SettingsService(session)
    service.set("llm_providers_json", "{}")

    result = await run_llm_provider_tests(service, create_client=fake_client)

    assert result == {"results": []}


@pytest.mark.asyncio
async def test_llm_provider_test_skips_unknown_providers_and_tolerates_bad_priority(session):
    service = SettingsService(session)
    service.set(
        "llm_providers_json",
        json.dumps(
            [
                {
                    "provider": "unknown",
                    "enabled": True,
                    "priority": 1,
                    "model": "unknown-model",
                    "api_key": "valid-key",
                    "base_url": "https://example.com/v1",
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

    result = await run_llm_provider_tests(service, create_client=fake_client)

    assert len(result["results"]) == 1
    assert result["results"][0]["provider"] == "openai"
    assert result["results"][0]["success"] is True
    assert result["results"][0]["message"] == "ok"


@pytest.mark.asyncio
async def test_llm_provider_test_treats_string_false_as_disabled(session):
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

    result = await run_llm_provider_tests(service, create_client=fake_client)

    assert [item["provider"] for item in result["results"]] == ["ollama"]


@pytest.mark.asyncio
async def test_llm_provider_test_redacts_credentials_from_error_response(session):
    service = SettingsService(session)
    service.set(
        "llm_providers_json",
        json.dumps(
            [
                {
                    "provider": "gemini",
                    "enabled": True,
                    "priority": 1,
                    "model": "gemini-2.0-flash",
                    "api_key": "stored-gemini-secret",
                    "base_url": "https://generativelanguage.googleapis.com/v1",
                }
            ]
        ),
    )

    result = await run_llm_provider_tests(service, create_client=failing_gemini_client)

    assert "stored-gemini-secret" not in result["results"][0]["message"]
    assert "key=********" in result["results"][0]["message"]


@pytest.mark.asyncio
async def test_llm_provider_test_rejects_too_many_temporary_providers(session):
    service = SettingsService(session)
    providers = [
        {
            "provider": "openai",
            "enabled": True,
            "priority": index,
            "model": "gpt-4o-mini",
            "api_key": "key",
            "base_url": "https://api.openai.com/v1",
        }
        for index in range(9)
    ]

    with pytest.raises(Exception) as error:
        await run_llm_provider_tests(
            service,
            {"providers": providers},
            create_client=fake_client,
        )

    assert getattr(error.value, "status_code", None) == 422

import json

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.services import llm_client as llm_client_module
from app.services.llm_client import (
    AnthropicClient,
    GeminiClient,
    OpenAIClient,
    _valid_filter_indices,
    create_llm_filter_client,
)
from app.services.settings_service import SettingsService


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class _FakeAsyncClient:
    payload = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return _FakeResponse(self.payload)


@pytest.mark.asyncio
async def test_openai_client_tolerates_empty_choices(monkeypatch):
    _FakeAsyncClient.payload = {"choices": []}
    monkeypatch.setattr(llm_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    client = OpenAIClient(api_key="key", base_url="https://example.com/v1")
    content = await client.chat("hello", "model")

    assert content == ""
    assert client.last_error == ""
    assert "content was empty" in client.last_detail


def test_valid_filter_indices_deduplicates_and_bounds_indices():
    assert _valid_filter_indices("[0, 0, 2, 4, -1, true]", batch_size=3) == [0, 2]
    assert _valid_filter_indices("not-json", batch_size=3) == []


def test_valid_filter_indices_extracts_array_from_wrapped_llm_text():
    assert _valid_filter_indices("```json\n[1, 0]\n```\n说明", batch_size=3) == [1, 0]
    assert _valid_filter_indices("keep these: [2]", batch_size=3) == [2]
    assert _valid_filter_indices("[]", batch_size=3) == []


@pytest.mark.asyncio
async def test_anthropic_client_tolerates_empty_content(monkeypatch):
    _FakeAsyncClient.payload = {"content": []}
    monkeypatch.setattr(llm_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    client = AnthropicClient(api_key="key")
    content = await client.chat("hello", "model")

    assert content == ""
    assert client.last_error == ""
    assert "content was empty" in client.last_detail


@pytest.mark.asyncio
async def test_gemini_client_tolerates_empty_candidates(monkeypatch):
    _FakeAsyncClient.payload = {"candidates": []}
    monkeypatch.setattr(llm_client_module.httpx, "AsyncClient", _FakeAsyncClient)

    client = GeminiClient(api_key="key")
    content = await client.chat("hello", "model")

    assert content == ""
    assert client.last_error == ""
    assert "content was empty" in client.last_detail


def test_llm_filter_skips_native_protocol_provider_for_openai_compatible_provider(monkeypatch):
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    seen = {}

    class FilterResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "[0]"}}]}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs["headers"]
        return FilterResponse()

    monkeypatch.setattr(llm_client_module.httpx, "post", fake_post)
    with Session(engine) as session:
        SettingsService(session).set(
            "llm_providers_json",
            json.dumps(
                [
                    {
                        "provider": "anthropic",
                        "enabled": True,
                        "priority": 1,
                        "model": "claude",
                        "api_key": "anthropic-key",
                        "base_url": "https://api.anthropic.com/v1",
                    },
                    {
                        "provider": "qwen",
                        "enabled": True,
                        "priority": 2,
                        "model": "qwen-plus",
                        "api_key": "qwen-key",
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    },
                ]
            ),
        )
        llm_filter = create_llm_filter_client(session)

        assert llm_filter is not None
        result = llm_filter(
            [{"title": "A", "original_summary": "B"}],
            type("Config", (), {"prompt": "keep", "mode": "must_pass"})(),
        )

    assert result == [{"title": "A", "original_summary": "B"}]
    assert seen["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer qwen-key"

import pytest

from app.services.agent.reranker import validate_matches_with_llm
from app.services.agent.schemas import AgentModMatch


def _match(mod_id: int, title: str) -> AgentModMatch:
    return AgentModMatch(
        id=mod_id,
        title=title,
        source="loverslab",
        game="Skyrim Special Edition",
        author=None,
        version=None,
        url=f"https://example.com/{mod_id}",
        updated_at_remote=None,
        score=10,
        original_summary="Roleplay content.",
    )


class _FakeRerankClient:
    async def chat(self, prompt, model, max_tokens=200):  # noqa: ARG002
        return '{"items":[{"id":true,"score":1.0},{"id":"2","score":0.8},{"id":0,"score":1.0}]}'


@pytest.mark.asyncio
async def test_reranker_ignores_bool_and_non_positive_ids(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent.reranker.create_llm_client",
        lambda **kwargs: _FakeRerankClient(),  # noqa: ARG005
    )

    result = await validate_matches_with_llm(
        query="bimbo roleplay",
        matches=[_match(1, "Wrongly scored by bool"), _match(2, "Valid numeric string id")],
        provider="openai",
        api_key="key",
        base_url="https://example.test/v1",
        model="test-model",
    )

    assert [item.id for item in result] == [2]

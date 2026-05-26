import logging

import pytest

from app.services.agent.schemas import AgentModMatch
from app.services.agent.tools.llm_candidate_validator_tool import (
    LlmCandidateValidatorInput,
    LlmCandidateValidatorTool,
)


def _match(title: str, match_id: int = 1) -> AgentModMatch:
    return AgentModMatch(
        id=match_id,
        title=title,
        source="nexusmods",
        game="Skyrim Special Edition",
        game_domain="skyrimspecialedition",
        category="Gameplay",
        author=None,
        version=None,
        url=f"https://example.com/{match_id}",
        updated_at_remote=None,
        adult_content=False,
        score=10,
        original_summary="Roleplay framework.",
    )


@pytest.mark.asyncio
async def test_llm_candidate_validator_skips_when_llm_unavailable(caplog):
    caplog.set_level(logging.INFO)
    match = _match("Bimbo Roleplay Framework")

    output = await LlmCandidateValidatorTool().run(
        LlmCandidateValidatorInput(query="bimbo roleplay", matches=[match], llm_available=False, evidence_id="ev_test")
    )

    assert output.matches == [match]
    assert output.status == "skipped"
    assert output.reason == "llm_unavailable"
    assert any("agent.tool name=llm_candidate_validator status=skipped reason=llm_unavailable" in item.message for item in caplog.records)


@pytest.mark.asyncio
async def test_llm_candidate_validator_runs_injected_validator(caplog):
    caplog.set_level(logging.INFO)
    first = _match("Weak Match", 1)
    second = _match("Strong Match", 2)

    async def fake_validator(**kwargs):
        assert kwargs["query"] == "bimbo roleplay"
        assert kwargs["matches"] == [first, second]
        return [second]

    output = await LlmCandidateValidatorTool(validator=fake_validator).run(
        LlmCandidateValidatorInput(
            query="bimbo roleplay",
            matches=[first, second],
            llm_available=True,
            provider="test",
            api_key="key",
            model="model",
            query_plan={"keywords": ["bimbo"]},
            evidence_id="ev_test",
        )
    )

    assert output.matches == [second]
    assert output.status == "succeeded"
    assert any("agent.tool name=llm_candidate_validator status=succeeded input=2 output=1" in item.message for item in caplog.records)


@pytest.mark.asyncio
async def test_llm_candidate_validator_degrades_to_original_matches_on_error(caplog):
    caplog.set_level(logging.INFO)
    match = _match("Bimbo Roleplay Framework")

    async def failing_validator(**kwargs):
        raise RuntimeError("llm down")

    output = await LlmCandidateValidatorTool(validator=failing_validator).run(
        LlmCandidateValidatorInput(query="bimbo roleplay", matches=[match], llm_available=True, evidence_id="ev_test")
    )

    assert output.matches == [match]
    assert output.status == "degraded"
    assert output.reason == "RuntimeError"
    assert any("agent.tool name=llm_candidate_validator status=degraded reason=RuntimeError" in item.message for item in caplog.records)

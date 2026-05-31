import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.planning.open_discovery_policy import is_open_discovery_plan
from app.services.agent.reranker import validate_matches_with_llm
from app.services.agent.schemas import AgentModMatch

logger = logging.getLogger(__name__)

CandidateValidator = Callable[..., Awaitable[list[AgentModMatch]]]


@dataclass(frozen=True)
class LlmCandidateValidatorInput:
    query: str
    matches: list[AgentModMatch] = field(default_factory=list)
    llm_available: bool = False
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    query_plan: dict[str, Any] = field(default_factory=dict)
    evidence_id: str = ""


@dataclass(frozen=True)
class LlmCandidateValidatorOutput:
    matches: list[AgentModMatch]
    status: str
    reason: str | None = None


class LlmCandidateValidatorTool:
    """非开放发现路径的轻量 LLM 校验；开放发现相关性统一交给 CandidateSemanticJudgeTool。"""

    name = "llm_candidate_validator"

    def __init__(self, *, validator: CandidateValidator = validate_matches_with_llm):
        self.validator = validator

    async def run(self, tool_input: LlmCandidateValidatorInput) -> LlmCandidateValidatorOutput:
        if not tool_input.matches:
            return self._skip(tool_input, reason="no_matches")
        if not tool_input.llm_available:
            return self._skip(tool_input, reason="llm_unavailable")
        if is_open_discovery_plan(tool_input.query_plan):
            return self._skip(tool_input, reason="semantic_judge_primary")
        try:
            validated = await self.validator(
                query=tool_input.query,
                matches=tool_input.matches,
                provider=tool_input.provider,
                api_key=tool_input.api_key,
                base_url=tool_input.base_url,
                model=tool_input.model,
                query_plan=tool_input.query_plan,
            )
        except Exception as exc:  # pragma: no cover - defensive degradation path
            logger.warning(
                "agent.tool name=llm_candidate_validator status=degraded reason=%s count=%s evidence_id=%s",
                type(exc).__name__,
                len(tool_input.matches),
                tool_input.evidence_id,
            )
            return LlmCandidateValidatorOutput(
                matches=tool_input.matches,
                status="degraded",
                reason=type(exc).__name__,
            )
        logger.info(
            "agent.tool name=llm_candidate_validator status=succeeded input=%s output=%s evidence_id=%s",
            len(tool_input.matches),
            len(validated),
            tool_input.evidence_id,
        )
        return LlmCandidateValidatorOutput(matches=validated, status="succeeded")

    def _skip(self, tool_input: LlmCandidateValidatorInput, *, reason: str) -> LlmCandidateValidatorOutput:
        logger.info(
            "agent.tool name=llm_candidate_validator status=skipped reason=%s count=%s evidence_id=%s",
            reason,
            len(tool_input.matches),
            tool_input.evidence_id,
        )
        return LlmCandidateValidatorOutput(matches=tool_input.matches, status="skipped", reason=reason)

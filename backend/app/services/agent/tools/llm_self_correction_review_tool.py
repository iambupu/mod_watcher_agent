import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.services.agent.self_correction.llm_self_correction_prompt import (
    build_llm_self_correction_review_prompt,
    build_llm_self_correction_review_repair_prompt,
)
from app.services.agent.self_correction.self_correction_evidence import SelfCorrectionEvidence
from app.services.agent.self_correction.self_correction_schema import (
    LLMSelfCorrectionReviewResult,
    SelfCorrectionPhase,
)
from app.services.llm_client import LLMClient, create_llm_client
from app.utils.json import json_object_from_text

logger = logging.getLogger(__name__)

ReviewCallable = Callable[["LLMSelfCorrectionReviewInput"], Awaitable[LLMSelfCorrectionReviewResult | dict]]
ClientFactory = Callable[[str, str, str], LLMClient]


@dataclass(frozen=True)
class LLMSelfCorrectionReviewInput:
    evidence: SelfCorrectionEvidence
    round_index: int
    max_rounds: int
    phase: SelfCorrectionPhase
    llm_available: bool = False
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    evidence_id: str = ""


class LLMSelfCorrectionReviewTool:
    """Mandatory LLM review node for self-correction decisions."""

    name = "llm_self_correction_review"

    def __init__(
        self,
        *,
        reviewer: ReviewCallable | None = None,
        client_factory: ClientFactory = create_llm_client,
    ):
        self.reviewer = reviewer
        self.client_factory = client_factory

    async def run(self, tool_input: LLMSelfCorrectionReviewInput) -> LLMSelfCorrectionReviewResult:
        if not tool_input.llm_available or not tool_input.provider or not tool_input.model:
            return _unavailable_result("llm_review_required_but_unavailable")
        try:
            if self.reviewer is not None:
                return _coerce_review_result(await self.reviewer(tool_input), status="passed")
            result = await _run_llm_review(tool_input, client_factory=self.client_factory)
        except Exception as exc:  # pragma: no cover - defensive degradation path
            logger.warning(
                "agent.tool name=llm_self_correction_review status=unavailable reason=%s evidence_id=%s",
                type(exc).__name__,
                tool_input.evidence_id,
            )
            return _unavailable_result(type(exc).__name__)
        return result


async def _run_llm_review(
    tool_input: LLMSelfCorrectionReviewInput,
    *,
    client_factory: ClientFactory,
) -> LLMSelfCorrectionReviewResult:
    prompt = build_llm_self_correction_review_prompt(
        evidence=tool_input.evidence,
        round_index=tool_input.round_index,
        max_rounds=tool_input.max_rounds,
        phase=tool_input.phase,
    )
    client = client_factory(tool_input.provider, tool_input.api_key, tool_input.base_url)
    content = await client.chat(prompt, model=tool_input.model, max_tokens=900, request_timeout=25.0)
    result = _result_from_json(json_object_from_text(content), raw_output=content, status="passed")
    if result is not None:
        logger.info(
            "agent.tool name=llm_self_correction_review status=passed action=%s evidence_id=%s",
            result.action,
            tool_input.evidence_id,
        )
        return result
    repair_text = await client.chat(
        build_llm_self_correction_review_repair_prompt(original_prompt=prompt, invalid_output=content),
        model=tool_input.model,
        max_tokens=900,
        request_timeout=25.0,
    )
    repaired = _result_from_json(json_object_from_text(repair_text), raw_output=repair_text, status="repaired")
    if repaired is not None:
        logger.info(
            "agent.tool name=llm_self_correction_review status=repaired action=%s evidence_id=%s",
            repaired.action,
            tool_input.evidence_id,
        )
        return repaired
    logger.info(
        "agent.tool name=llm_self_correction_review status=invalid reason=invalid_repair_json evidence_id=%s",
        tool_input.evidence_id,
    )
    return _invalid_result(content or repair_text)


def _result_from_json(
    value: dict | None,
    *,
    raw_output: str,
    status: str,
) -> LLMSelfCorrectionReviewResult | None:
    if not isinstance(value, dict):
        return None
    try:
        result = LLMSelfCorrectionReviewResult.model_validate(value)
    except Exception:
        return None
    result.llm_review_status = status
    result.used_llm = True
    result.raw_output = raw_output
    return result


def _coerce_review_result(
    value: LLMSelfCorrectionReviewResult | dict,
    *,
    status: str,
) -> LLMSelfCorrectionReviewResult:
    result = value if isinstance(value, LLMSelfCorrectionReviewResult) else LLMSelfCorrectionReviewResult.model_validate(value)
    result.llm_review_status = status
    result.used_llm = True
    return result


def _unavailable_result(reason: str) -> LLMSelfCorrectionReviewResult:
    return LLMSelfCorrectionReviewResult(
        action="fallback_no_direct_match",
        detected_errors=["llm_review_unavailable"],
        reason_summary="LLM Review 是自我修正必需路径，但当前不可用，不能进入多轮修正成功路径。",
        correction_plan={},
        changed_fields=[],
        preserved_constraints=[],
        rejected_changes=[reason],
        confidence=0.0,
        llm_review_status="unavailable",
        used_llm=False,
        fallback_reason=reason,
    )


def _invalid_result(raw_output: str) -> LLMSelfCorrectionReviewResult:
    return LLMSelfCorrectionReviewResult(
        action="fallback_no_direct_match",
        detected_errors=["llm_review_invalid_output"],
        reason_summary="LLM Review 输出在一次修复后仍不是合法结构，不能进入多轮修正成功路径。",
        correction_plan={},
        changed_fields=[],
        preserved_constraints=[],
        rejected_changes=["invalid_llm_review_json"],
        confidence=0.0,
        llm_review_status="invalid",
        used_llm=True,
        raw_output=raw_output,
        fallback_reason="invalid_llm_review_json",
    )

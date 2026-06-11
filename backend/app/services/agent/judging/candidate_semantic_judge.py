import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.services.agent.judging.candidate_semantic_judge_prompt import (
    build_candidate_semantic_judge_prompt,
    build_candidate_semantic_judge_repair_prompt,
)
from app.services.agent.schemas import AgentModMatch
from app.services.llm_client import create_llm_client
from app.utils.ids import positive_integer_id
from app.utils.json import json_object_from_text

logger = logging.getLogger(__name__)
DEFAULT_CANDIDATE_SEMANTIC_JUDGE_TIMEOUT_SECONDS = 90.0
CANDIDATE_SEMANTIC_JUDGE_TIMEOUT_SECONDS = DEFAULT_CANDIDATE_SEMANTIC_JUDGE_TIMEOUT_SECONDS

JudgeRelevance = Literal["high", "medium", "low", "reject"]
JudgeFitType = Literal["direct_match", "support_context", "off_scope", "uncertain"]
CategorySemanticCompatibility = Literal["compatible", "ambiguous", "incompatible", "not_applicable"]
JudgeGroup = Literal[
    "core_gameplay",
    "visual_support",
    "follower_or_npc",
    "requirement_or_patch",
    "related_addon",
    "other_related",
    "off_topic",
]


class CandidateSemanticJudgement(BaseModel):
    # relevance 决定排序和是否进入回答：high/medium 优先，low 只做补充，reject 直接剔除。
    candidate_id: int
    relevance: JudgeRelevance = "low"
    fit_type: JudgeFitType = "uncertain"
    group: JudgeGroup = "other_related"
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    category_semantic_compatibility: CategorySemanticCompatibility = "not_applicable"
    category_compatibility_reason: str = ""

    @field_validator("candidate_id", mode="before")
    @classmethod
    def _normalize_candidate_id(cls, value: object) -> int:
        return _positive_candidate_id(value)

    @field_validator("reason", mode="before")
    @classmethod
    def _strip_reason(cls, value: object) -> str:
        return str(value or "").strip()[:240]

    @field_validator("category_compatibility_reason", mode="before")
    @classmethod
    def _strip_category_reason(cls, value: object) -> str:
        return str(value or "").strip()[:240]

    @field_validator("evidence", "violations", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        values: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in values:
                values.append(text[:160])
        return values[:8]


class CandidateSemanticGroup(BaseModel):
    name: JudgeGroup = "other_related"
    label: str = ""
    candidate_ids: list[int] = Field(default_factory=list)
    reason: str = ""

    @field_validator("label", "reason", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> str:
        return str(value or "").strip()[:240]

    @field_validator("candidate_ids", mode="before")
    @classmethod
    def _normalize_ids(cls, value: object) -> list[int]:
        if not isinstance(value, list):
            return []
        ids: list[int] = []
        for item in value:
            try:
                candidate_id = _positive_candidate_id(item)
            except (TypeError, ValueError):
                continue
            if candidate_id not in ids:
                ids.append(candidate_id)
        return ids[:20]


class CandidateSemanticRejected(BaseModel):
    candidate_id: int
    reason: str = ""

    @field_validator("candidate_id", mode="before")
    @classmethod
    def _normalize_candidate_id(cls, value: object) -> int:
        return _positive_candidate_id(value)

    @field_validator("reason", mode="before")
    @classmethod
    def _strip_reason(cls, value: object) -> str:
        return str(value or "").strip()[:240]


class CandidateSemanticJudgeResult(BaseModel):
    """候选语义裁判结果只解释已有候选，不负责凭空生成 MOD 或执行补查。"""

    judgements: list[CandidateSemanticJudgement] = Field(default_factory=list)
    groups: list[CandidateSemanticGroup] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    rejected: list[CandidateSemanticRejected] = Field(default_factory=list)
    fallback_reason: str = ""
    used_llm: bool = False
    status: Literal["succeeded", "skipped", "fallback", "degraded", "disabled"] = "fallback"
    raw_output: str | None = None

    @field_validator("gaps", mode="before")
    @classmethod
    def _normalize_gaps(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        gaps: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in gaps:
                gaps.append(text[:160])
        return gaps[:8]


@dataclass(frozen=True)
class CandidateSemanticJudgeInput:
    query: str
    semantic_strategy: dict[str, Any] = field(default_factory=dict)
    candidates: list[AgentModMatch] = field(default_factory=list)
    retrieval_evidence: list[dict[str, object]] = field(default_factory=list)
    llm_available: bool = False
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    evidence_id: str = ""


JudgeCallable = Callable[[CandidateSemanticJudgeInput], Awaitable[CandidateSemanticJudgeResult | dict[str, Any]]]


class CandidateSemanticJudgeTool:
    """开放发现的语义中心：先宽召回，再让 LLM 裁判候选是否真正相关。"""

    name = "candidate_semantic_judge"

    def __init__(self, *, judge: JudgeCallable | None = None):
        self.judge = judge

    async def run(self, tool_input: CandidateSemanticJudgeInput) -> CandidateSemanticJudgeResult:
        if not _enabled():
            return _fallback_result(tool_input, status="disabled", reason="feature_disabled")
        if not tool_input.candidates:
            return _fallback_result(tool_input, status="skipped", reason="no_candidates")
        if not tool_input.llm_available:
            return _fallback_result(tool_input, status="skipped", reason="llm_unavailable")
        try:
            if self.judge is not None:
                return _coerce_result(await self.judge(tool_input), status="succeeded", used_llm=True)
            result = await _run_llm_judge(tool_input)
        except Exception as exc:  # pragma: no cover - defensive degradation path
            logger.warning(
                "agent.tool name=candidate_semantic_judge status=degraded reason=%s candidates=%s evidence_id=%s",
                type(exc).__name__,
                len(tool_input.candidates),
                tool_input.evidence_id,
            )
            return _fallback_result(tool_input, status="degraded", reason=type(exc).__name__)
        if result is None:
            return _fallback_result(tool_input, status="fallback", reason="invalid_llm_json")
        return result


async def _run_llm_judge(tool_input: CandidateSemanticJudgeInput) -> CandidateSemanticJudgeResult | None:
    prompt = build_candidate_semantic_judge_prompt(
        query=tool_input.query,
        semantic_strategy=tool_input.semantic_strategy,
        candidates=tool_input.candidates,
        retrieval_evidence=tool_input.retrieval_evidence,
    )
    client = create_llm_client(
        provider=tool_input.provider,
        api_key=tool_input.api_key,
        base_url=tool_input.base_url,
    )
    request_timeout = _request_timeout_seconds()
    try:
        content = await client.chat(
            prompt,
            model=tool_input.model,
            max_tokens=1400,
            request_timeout=request_timeout,
        )
    except TimeoutError as exc:
        logger.info(
            "agent.tool name=candidate_semantic_judge status=fallback reason=timeout timeout_seconds=%s evidence_id=%s",
            request_timeout,
            tool_input.evidence_id,
        )
        raise exc
    result = _result_from_json(json_object_from_text(content), raw_output=content)
    if result is not None:
        logger.info(
            "agent.tool name=candidate_semantic_judge status=succeeded candidates=%s judgements=%s timeout_seconds=%s evidence_id=%s",
            len(tool_input.candidates),
            len(result.judgements),
            request_timeout,
            tool_input.evidence_id,
        )
        return result
    repair_text = await client.chat(
        build_candidate_semantic_judge_repair_prompt(original_prompt=prompt, invalid_output=content),
        model=tool_input.model,
        max_tokens=1400,
        request_timeout=request_timeout,
    )
    repaired = _result_from_json(json_object_from_text(repair_text), raw_output=repair_text)
    if repaired is None:
        logger.info(
            "agent.tool name=candidate_semantic_judge status=fallback reason=invalid_repair_json timeout_seconds=%s evidence_id=%s",
            request_timeout,
            tool_input.evidence_id,
        )
        return None
    logger.info(
        "agent.tool name=candidate_semantic_judge status=succeeded source=repair candidates=%s judgements=%s timeout_seconds=%s evidence_id=%s",
        len(tool_input.candidates),
        len(repaired.judgements),
        request_timeout,
        tool_input.evidence_id,
    )
    return repaired


def _request_timeout_seconds() -> float:
    raw = os.getenv("MW_AGENT_CANDIDATE_SEMANTIC_JUDGE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_CANDIDATE_SEMANTIC_JUDGE_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_CANDIDATE_SEMANTIC_JUDGE_TIMEOUT_SECONDS
    return min(180.0, max(10.0, value))


def _result_from_json(value: dict | None, *, raw_output: str) -> CandidateSemanticJudgeResult | None:
    if not isinstance(value, dict):
        return None
    try:
        result = CandidateSemanticJudgeResult.model_validate(value)
    except Exception:
        return None
    _drop_stale_no_direct_gaps(result)
    result.used_llm = True
    result.status = "succeeded"
    result.raw_output = raw_output
    return result


def _coerce_result(
    value: CandidateSemanticJudgeResult | dict[str, Any],
    *,
    status: str,
    used_llm: bool,
) -> CandidateSemanticJudgeResult:
    result = value if isinstance(value, CandidateSemanticJudgeResult) else CandidateSemanticJudgeResult.model_validate(value)
    _drop_stale_no_direct_gaps(result)
    result.status = status
    result.used_llm = used_llm
    return result


def _fallback_result(tool_input: CandidateSemanticJudgeInput, *, status: str, reason: str) -> CandidateSemanticJudgeResult:
    # fallback 只保持原排序和可解释证据，不尝试复制 LLM 的语义裁判能力。
    return CandidateSemanticJudgeResult(
        judgements=[
            CandidateSemanticJudgement(
                candidate_id=item.id,
                relevance="low",
                fit_type="uncertain",
                group="other_related",
                reason="fallback_keep_original_candidate",
                evidence=["fallback_original_order"],
                category_semantic_compatibility="not_applicable",
            )
            for item in tool_input.candidates
        ],
        groups=[
            CandidateSemanticGroup(
                name="other_related",
                label="相关候选",
                candidate_ids=[item.id for item in tool_input.candidates[:20]],
                reason="fallback_original_order",
            )
        ],
        fallback_reason=reason,
        used_llm=False,
        status=status,  # type: ignore[arg-type]
    )


def build_candidate_semantic_judge_evidence(
    result: CandidateSemanticJudgeResult,
    *,
    input_count: int,
    output_count: int,
    evidence_id: str,
) -> dict[str, object]:
    rejected_ids = {item.candidate_id for item in result.rejected}
    rejected_ids.update(item.candidate_id for item in result.judgements if item.relevance == "reject")
    fit_counts = {"direct_match": 0, "support_context": 0, "off_scope": 0, "uncertain": 0}
    category_compatibility_counts = {
        "compatible": 0,
        "ambiguous": 0,
        "incompatible": 0,
        "not_applicable": 0,
    }
    for item in result.judgements:
        fit_counts[item.fit_type] = fit_counts.get(item.fit_type, 0) + 1
        category_compatibility_counts[item.category_semantic_compatibility] = (
            category_compatibility_counts.get(item.category_semantic_compatibility, 0) + 1
        )
    return {
        "fragment_id": "r_candidate_semantic_judge_1",
        "stage": "final_ranking",
        "tool": CandidateSemanticJudgeTool.name,
        "status": result.status,
        "used_llm": result.used_llm,
        "timeout_seconds": _request_timeout_seconds(),
        "input_count": input_count,
        "output_count": output_count,
        "rejected_count": len(rejected_ids),
        "fit_counts": fit_counts,
        "category_compatibility_counts": category_compatibility_counts,
        "groups": [
            {
                "name": group.name,
                "label": group.label,
                "count": len(group.candidate_ids),
                "reason": group.reason,
            }
            for group in result.groups
        ],
        "gaps": result.gaps,
        "fallback_reason": result.fallback_reason,
        "evidence_id": evidence_id,
    }


def _enabled() -> bool:
    raw = os.getenv("MW_AGENT_CANDIDATE_SEMANTIC_JUDGE_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _positive_candidate_id(value: object) -> int:
    candidate_id = positive_integer_id(value, allow_string=True)
    if candidate_id is None:
        raise ValueError("candidate_id must be a positive integer")
    return candidate_id


def _drop_stale_no_direct_gaps(result: CandidateSemanticJudgeResult) -> None:
    if not any(item.fit_type == "direct_match" for item in result.judgements):
        return
    result.gaps = [
        gap
        for gap in result.gaps
        if not _is_no_direct_match_gap(gap)
    ]


def _is_no_direct_match_gap(value: str) -> bool:
    text = str(value or "").strip().lower()
    markers = (
        "direct_match不足",
        "direct match不足",
        "no direct",
        "没有直接匹配",
        "没有直接命中",
        "未找到明确的直接匹配",
        "未找到明确的直接命中",
        "缺少直接匹配",
        "缺少直接命中",
        "缺少标题或描述中明确包含",
        "标题或描述中明确包含",
        "直接匹配不足",
        "直接命中不足",
    )
    if any(marker in text for marker in markers):
        return True
    if "缺少明确提及" in text and ("标题" in text or "描述" in text):
        return True
    return "明确标注" in text and ("直接匹配" in text or "直接命中" in text)

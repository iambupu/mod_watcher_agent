from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.services.agent.list_utils import string_list, unique_text

SelfCorrectionPhase = Literal["round_review", "post_correction_review", "final_answer_review"]
SelfCorrectionReviewStatus = Literal["passed", "invalid", "repaired", "unavailable", "blocked"]
SelfCorrectionAction = Literal[
    "continue_answer",
    "repair_query_plan",
    "refine_retrieval",
    "rejudge_candidates",
    "rewrite_answer",
    "fallback_no_direct_match",
    "ask_clarification",
    "fallback",
]
SelfCorrectionFinalStatus = Literal["not_started", "answered", "fallback", "clarification_needed", "llm_review_unavailable"]


class SelfCorrectionConfig(BaseModel):
    enabled: bool = True
    llm_review_required: bool = True
    max_rounds: int = Field(default=2, ge=1, le=3)
    min_direct_matches: int = Field(default=3, ge=0, le=20)
    allow_hard_constraint_relaxation: bool = False
    allow_rule_only_review: bool = False


class SelfCorrectionRound(BaseModel):
    round_index: int = Field(ge=1)
    phase: SelfCorrectionPhase
    llm_review_status: SelfCorrectionReviewStatus
    action: SelfCorrectionAction
    detected_errors: list[str] = Field(default_factory=list)
    reason_summary: str = ""
    changed_fields: list[str] = Field(default_factory=list)
    preserved_constraints: list[str] = Field(default_factory=list)
    rejected_changes: list[str] = Field(default_factory=list)
    candidate_counts_before: dict[str, int] = Field(default_factory=dict)
    candidate_counts_after: dict[str, int] | None = None

    @field_validator("detected_errors", "changed_fields", "preserved_constraints", "rejected_changes", mode="before")
    @classmethod
    def _normalize_text_list(cls, value: object) -> list[str]:
        return unique_text(string_list(value), limit=24)

    @field_validator("reason_summary", mode="before")
    @classmethod
    def _compact_reason_summary(cls, value: object) -> str:
        return str(value or "").strip()[:500]


class SelfCorrectionTrace(BaseModel):
    enabled: bool = True
    llm_review_required: bool = True
    max_rounds: int = Field(default=2, ge=1, le=3)
    rounds: list[SelfCorrectionRound] = Field(default_factory=list)
    final_status: SelfCorrectionFinalStatus = "not_started"


class LLMSelfCorrectionReviewResult(BaseModel):
    action: SelfCorrectionAction
    detected_errors: list[str] = Field(default_factory=list)
    reason_summary: str = ""
    correction_plan: dict[str, Any] = Field(default_factory=dict)
    changed_fields: list[str] = Field(default_factory=list)
    preserved_constraints: list[str] = Field(default_factory=list)
    rejected_changes: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    llm_review_status: SelfCorrectionReviewStatus = "passed"
    used_llm: bool = True
    raw_output: str | None = None
    fallback_reason: str = ""

    @field_validator("detected_errors", "changed_fields", "preserved_constraints", "rejected_changes", mode="before")
    @classmethod
    def _normalize_text_list(cls, value: object) -> list[str]:
        return unique_text(string_list(value), limit=24)

    @field_validator("reason_summary", "fallback_reason", mode="before")
    @classmethod
    def _compact_text(cls, value: object) -> str:
        return str(value or "").strip()[:500]


def default_self_correction_config() -> dict[str, Any]:
    return SelfCorrectionConfig().model_dump(mode="python")


def with_default_self_correction_config(query_plan: dict[str, Any]) -> dict[str, Any]:
    plan = dict(query_plan or {})
    raw_config = plan.get("_agent_self_correction_config")
    if isinstance(raw_config, dict):
        try:
            config = SelfCorrectionConfig.model_validate(raw_config)
        except ValueError:
            config = SelfCorrectionConfig()
    else:
        config = SelfCorrectionConfig()
    plan["_agent_self_correction_config"] = config.model_dump(mode="python")
    return plan

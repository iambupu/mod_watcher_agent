from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic.config import ConfigDict

from app.services.agent.list_utils import unique_text
from app.services.agent.slot_aliases import normalize_source_alias

SemanticTaskType = Literal[
    "exact_lookup",
    "open_discovery",
    "comparative",
    "advisory",
    "preference",
    "unknown",
]

SemanticRetrievalStrategy = Literal[
    "exact_then_explain",
    "broad_then_judge",
    "compare_known_and_fetch_missing",
    "evidence_then_advice",
    "memory_summary",
    "clarify_first",
]

AnswerShape = Literal[
    "direct_lookup",
    "grouped_recommendation",
    "comparison_table",
    "risk_advice",
    "memory_summary",
    "clarify_first",
]


class SemanticHardFilters(BaseModel):
    """只有用户明确说死的条件才能进入 hard_filters，不能由记忆或软语义外推。"""

    model_config = ConfigDict(extra="allow")

    game: str | None = None
    source: str | None = None
    adult_content: bool | None = None
    exact_title: str | None = None
    external_id: str | None = None
    source_url: str | None = None
    excluded_keywords: list[str] = Field(default_factory=list)
    excluded_sources: list[str] = Field(default_factory=list)

    @field_validator("game", "source", "exact_title", "external_id", "source_url", mode="before")
    @classmethod
    def _strip_optional_string(cls, value: object) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("source", mode="after")
    @classmethod
    def _normalize_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_source_alias(value) or None

    @field_validator("excluded_keywords", "excluded_sources", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return unique_text((str(item or "").strip()[:120] for item in value), limit=12)

    @field_validator("excluded_sources", mode="after")
    @classmethod
    def _normalize_excluded_sources(cls, value: list[str]) -> list[str]:
        return unique_text((normalize_source_alias(item) for item in value), limit=12)


class SemanticStrategy(BaseModel):
    """LLM 语义决策对象，只描述用户目标和策略，不直接作为数据库查询参数。"""

    task_type: SemanticTaskType = "unknown"
    user_goal: str = ""
    strategy: SemanticRetrievalStrategy = "clarify_first"
    hard_filters: SemanticHardFilters = Field(default_factory=SemanticHardFilters)
    core_terms: list[str] = Field(default_factory=list)
    soft_signals: list[str] = Field(default_factory=list)
    ranking_goal: str = ""
    answer_shape: AnswerShape = "clarify_first"
    confidence: float = 0.0
    reason: str = ""

    @field_validator("user_goal", "ranking_goal", "reason", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> str:
        return str(value or "").strip()[:1000]

    @field_validator("core_terms", "soft_signals", mode="before")
    @classmethod
    def _normalize_terms(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return unique_text((str(item or "").strip()[:120] for item in value), limit=16)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: object) -> float:
        try:
            return max(0.0, min(float(value), 1.0))
        except (TypeError, ValueError):
            return 0.0


class SemanticStrategyResult(BaseModel):
    strategy: SemanticStrategy
    source: Literal["llm", "fallback", "disabled"] = "fallback"
    used_llm: bool = False
    status: Literal["succeeded", "fallback", "disabled", "degraded"] = "fallback"
    fallback_reason: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    raw_output: str | None = None

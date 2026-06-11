# 中文注释：实现 Agent 自校正证据收集和硬约束守卫。

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.agent.list_utils import string_list, unique_text
from app.services.agent.planning.query_plan_constraints import collect_hard_constraints
from app.services.agent.schemas import AgentModMatch

MAX_CANDIDATE_SNAPSHOT = 20
SUMMARY_SNIPPET_LIMIT = 260
TEXT_LIST_LIMIT = 12
RETRIEVAL_SUMMARY_KEYS = (
    "mode",
    "web_enabled",
    "web_queried",
    "query_plan",
    "retrieval_decision",
    "web_search",
    "candidate_semantic_judge",
    "self_correction",
)


class SelfCorrectionCandidateSnapshot(BaseModel):
    id: int
    title: str
    source: str
    game: str
    category: str | None = None
    summary_snippet: str = ""
    fit_type: str = "uncertain"
    evidence: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)

    @field_validator("title", "source", "game", "category", "summary_snippet", "fit_type", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("evidence", "violations", mode="before")
    @classmethod
    def _normalize_text_list(cls, value: object) -> list[str]:
        return unique_text(string_list(value), limit=4)


class SelfCorrectionEvidence(BaseModel):
    original_query: str
    current_goal: str
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    direct_match_definition: list[str] = Field(default_factory=list)
    support_context_definition: list[str] = Field(default_factory=list)
    reject_as_primary: list[str] = Field(default_factory=list)
    fit_counts: dict[str, int] = Field(default_factory=dict)
    candidate_snapshot: list[SelfCorrectionCandidateSnapshot] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    retrieval_summary: dict[str, Any] = Field(default_factory=dict)
    history_summary: str | None = None

    @field_validator("original_query", "current_goal", "history_summary", mode="before")
    @classmethod
    def _strip_compact_text(cls, value: object) -> str:
        return str(value or "").strip()[:1000]

    @field_validator("direct_match_definition", "support_context_definition", "reject_as_primary", "gaps", mode="before")
    @classmethod
    def _normalize_text_list(cls, value: object) -> list[str]:
        return unique_text(string_list(value), limit=TEXT_LIST_LIMIT)


def build_self_correction_evidence(
    *,
    original_query: str,
    query_plan: dict[str, Any],
    matches: list[AgentModMatch],
    retrieval_evidence: dict[str, Any] | None = None,
    history_summary: str | None = None,
) -> SelfCorrectionEvidence:
    strategy = _dict_value(query_plan.get("_agent_semantic_strategy"))
    judge = _dict_value(query_plan.get("_agent_candidate_semantic_judge"))
    judgements = _judgements_by_candidate_id(judge.get("judgements"))
    return SelfCorrectionEvidence(
        original_query=original_query,
        current_goal=str(strategy.get("user_goal") or original_query or "").strip(),
        hard_constraints=_hard_constraints(query_plan, strategy),
        direct_match_definition=string_list(strategy.get("direct_match_definition"), limit=TEXT_LIST_LIMIT),
        support_context_definition=string_list(strategy.get("support_context_definition"), limit=TEXT_LIST_LIMIT),
        reject_as_primary=string_list(strategy.get("reject_as_primary"), limit=TEXT_LIST_LIMIT),
        fit_counts=_fit_counts(judge, judgements),
        candidate_snapshot=_candidate_snapshot(matches, judgements),
        gaps=string_list(judge.get("gaps"), limit=TEXT_LIST_LIMIT),
        retrieval_summary=_retrieval_summary(retrieval_evidence),
        history_summary=history_summary,
    )


def _candidate_snapshot(
    matches: list[AgentModMatch], judgements: dict[int, dict[str, Any]]
) -> list[SelfCorrectionCandidateSnapshot]:
    snapshots: list[SelfCorrectionCandidateSnapshot] = []
    for item in matches[:MAX_CANDIDATE_SNAPSHOT]:
        judgement = judgements.get(item.id, {})
        snapshots.append(
            SelfCorrectionCandidateSnapshot(
                id=item.id,
                title=item.title,
                source=item.source,
                game=item.game,
                category=item.category,
                summary_snippet=_summary_snippet(item),
                fit_type=str(judgement.get("fit_type") or "uncertain"),
                evidence=string_list(judgement.get("evidence"), limit=4),
                violations=string_list(judgement.get("violations"), limit=4),
            )
        )
    return snapshots


def _summary_snippet(item: AgentModMatch) -> str:
    text = str(item.translated_summary or item.original_summary or item.rank_reason or "").strip()
    return text[:SUMMARY_SNIPPET_LIMIT]


def _judgements_by_candidate_id(value: object) -> dict[int, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[int, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            candidate_id = int(item.get("candidate_id"))
        except (TypeError, ValueError):
            continue
        result[candidate_id] = item
    return result


def _fit_counts(judge: dict[str, Any], judgements: dict[int, dict[str, Any]]) -> dict[str, int]:
    raw_counts = judge.get("fit_counts")
    if isinstance(raw_counts, dict):
        return {str(key): _safe_int(value) for key, value in raw_counts.items()}
    counts = {"direct_match": 0, "support_context": 0, "off_scope": 0, "uncertain": 0}
    for item in judgements.values():
        fit_type = str(item.get("fit_type") or "uncertain")
        counts[fit_type] = counts.get(fit_type, 0) + 1
    return counts


def _hard_constraints(query_plan: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    hard_filters = _dict_value(strategy.get("hard_filters"))
    return collect_hard_constraints(query_plan, hard_filters)


def _retrieval_summary(retrieval_evidence: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(retrieval_evidence, dict):
        return {}
    return {
        key: _compact_value(retrieval_evidence.get(key))
        for key in RETRIEVAL_SUMMARY_KEYS
        if retrieval_evidence.get(key) is not None
    }


def _compact_value(value: object) -> object:
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, dict):
        return {str(key): _compact_value(item) for key, item in list(value.items())[:20]}
    if isinstance(value, list):
        return [_compact_value(item) for item in value[:20]]
    return value


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

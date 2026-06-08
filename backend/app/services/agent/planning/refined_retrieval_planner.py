from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.services.agent.list_utils import merge_unique_text, string_list, unique_text
from app.services.agent.planning.query_plan_constraints import (
    canonical_constraint_field,
    collect_hard_constraints,
    constraint_values_equal,
)
from app.services.agent.planning.query_plan_hygiene import sanitize_query_plan_fields


@dataclass(frozen=True)
class RefinedRetrievalInput:
    original_query: str
    query_plan: dict[str, Any]
    semantic_strategy: dict[str, Any]
    correction_plan: dict[str, Any]
    detected_errors: list[str] = field(default_factory=list)
    round_index: int = 2


class RefinedRetrievalPlan(BaseModel):
    query_plan: dict[str, Any] = Field(default_factory=dict)
    retrieval_queries: list[str] = Field(default_factory=list)
    preserved_constraints: list[str] = Field(default_factory=list)
    removed_pollution: list[str] = Field(default_factory=list)
    reason_summary: str = ""


def build_refined_retrieval_plan(tool_input: RefinedRetrievalInput) -> RefinedRetrievalPlan:
    original_plan = dict(tool_input.query_plan or {})
    refined_plan = dict(original_plan)
    _preserve_hard_constraints(refined_plan, tool_input)
    _apply_correction_terms(refined_plan, tool_input)
    sanitized = sanitize_query_plan_fields(refined_plan, query=tool_input.original_query)
    retrieval_queries = _retrieval_queries(tool_input, sanitized)
    return RefinedRetrievalPlan(
        query_plan=sanitized,
        retrieval_queries=retrieval_queries,
        preserved_constraints=_preserved_constraints(sanitized, tool_input.semantic_strategy),
        removed_pollution=_removed_pollution(refined_plan, sanitized),
        reason_summary=_reason_summary(tool_input),
    )


def _preserve_hard_constraints(refined_plan: dict[str, Any], tool_input: RefinedRetrievalInput) -> None:
    hard_filters = _dict_value(tool_input.semantic_strategy.get("hard_filters"))
    for field_name, value in collect_hard_constraints(refined_plan, hard_filters).items():
        if refined_plan.get(field_name) not in (None, "", []):
            continue
        refined_plan[field_name] = value


def _apply_correction_terms(refined_plan: dict[str, Any], tool_input: RefinedRetrievalInput) -> None:
    correction_plan = tool_input.correction_plan or {}
    query_plan_update = correction_plan.get("query_plan")
    hard_constraints = collect_hard_constraints(refined_plan, _dict_value(tool_input.semantic_strategy.get("hard_filters")))
    if isinstance(query_plan_update, dict):
        for field_name, value in query_plan_update.items():
            canonical_field = canonical_constraint_field(field_name)
            if (
                canonical_field in hard_constraints
                and not constraint_values_equal(value, hard_constraints[canonical_field])
            ):
                continue
            refined_plan[field_name] = value
    direct_terms = _direct_match_terms(tool_input)
    correction_terms = _correction_terms(correction_plan)
    if direct_terms or correction_terms:
        refined_plan["keywords"] = merge_unique_text(
            string_list(refined_plan.get("keywords")),
            [*direct_terms, *correction_terms],
            limit=24,
        )


def _retrieval_queries(tool_input: RefinedRetrievalInput, refined_plan: dict[str, Any]) -> list[str]:
    terms = unique_text(
        [
            tool_input.original_query,
            *string_list(refined_plan.get("games") or refined_plan.get("game")),
            *string_list(refined_plan.get("sources") or refined_plan.get("source")),
            *string_list(refined_plan.get("keywords"), limit=12),
        ],
        limit=18,
    )
    query = " ".join(terms).strip()
    extra_queries = string_list(tool_input.correction_plan.get("retrieval_queries"), limit=2)
    return unique_text([query, *extra_queries], limit=3)


def _direct_match_terms(tool_input: RefinedRetrievalInput) -> list[str]:
    terms = string_list(tool_input.semantic_strategy.get("direct_match_definition"), limit=6)
    return [item for item in terms if item not in string_list(tool_input.semantic_strategy.get("support_context_definition"))]


def _correction_terms(correction_plan: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for field_name in ("keywords", "retrieval_terms", "direct_terms"):
        terms.extend(string_list(correction_plan.get(field_name), limit=8))
    return unique_text(terms, limit=16)


def _preserved_constraints(refined_plan: dict[str, Any], semantic_strategy: dict[str, Any]) -> list[str]:
    hard_filters = _dict_value(semantic_strategy.get("hard_filters"))
    return [f"{field_name}={value}" for field_name, value in collect_hard_constraints(refined_plan, hard_filters).items()]


def _removed_pollution(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    removed: list[str] = []
    for field_name in ("categories", "keywords", "category_hints"):
        before_values = set(string_list(before.get(field_name)))
        after_values = set(string_list(after.get(field_name)))
        for value in sorted(before_values - after_values):
            removed.append(f"hygiene_removed:{field_name}:{value}")
    if before.get("exact_title") and not after.get("exact_title"):
        removed.append("hygiene_removed:exact_title")
    return removed


def _reason_summary(tool_input: RefinedRetrievalInput) -> str:
    errors = "; ".join(string_list(tool_input.detected_errors, limit=4))
    return f"round={tool_input.round_index}; refine retrieval toward direct_match_definition; errors={errors}"[:500]


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}

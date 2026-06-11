# 中文注释：封装 Agent 工具层的query plan repair tool逻辑。

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.services.agent.list_utils import string_list, unique_text
from app.services.agent.planning.query_plan_constraints import (
    canonical_constraint_field,
    constraint_values_equal,
    protected_constraint_field_names,
)
from app.services.agent.planning.query_plan_hygiene import sanitize_query_plan_fields
from app.services.agent.self_correction.self_correction_evidence import SelfCorrectionEvidence


@dataclass(frozen=True)
class QueryPlanRepairInput:
    original_query: str
    query_plan: dict[str, Any]
    correction_plan: dict[str, Any]
    evidence: SelfCorrectionEvidence
    allowed_fields: set[str] = field(default_factory=set)


class QueryPlanRepairResult(BaseModel):
    query_plan: dict[str, Any] = Field(default_factory=dict)
    changed_fields: list[str] = Field(default_factory=list)
    removed_pollution: list[str] = Field(default_factory=list)
    preserved_constraints: list[str] = Field(default_factory=list)


class QueryPlanRepairTool:
    """Apply guarded self-correction changes to query_plan and rerun hygiene."""

    name = "query_plan_repair"

    def run(self, tool_input: QueryPlanRepairInput) -> QueryPlanRepairResult:
        original = dict(tool_input.query_plan or {})
        repaired = dict(original)
        removed_pollution = _remove_requested_fields(repaired, tool_input)
        _merge_safe_query_plan_updates(repaired, tool_input)
        sanitized = sanitize_query_plan_fields(repaired, query=tool_input.original_query)
        removed_pollution.extend(_hygiene_removed_items(repaired, sanitized))
        changed_fields = _changed_fields(original, sanitized)
        return QueryPlanRepairResult(
            query_plan=sanitized,
            changed_fields=changed_fields,
            removed_pollution=unique_text(removed_pollution, limit=32),
            preserved_constraints=_preserved_constraints(tool_input.evidence),
        )


def _remove_requested_fields(plan: dict[str, Any], tool_input: QueryPlanRepairInput) -> list[str]:
    removed: list[str] = []
    protected_fields = protected_constraint_field_names(tool_input.evidence.hard_constraints)
    for field_name in _requested_remove_fields(tool_input.correction_plan):
        if field_name in protected_fields:
            continue
        if field_name not in plan:
            continue
        plan.pop(field_name, None)
        removed.append(f"removed_field:{field_name}")
    return removed


def _merge_safe_query_plan_updates(plan: dict[str, Any], tool_input: QueryPlanRepairInput) -> None:
    updates = tool_input.correction_plan.get("query_plan")
    if not isinstance(updates, dict):
        updates = {
            key: value
            for key, value in tool_input.correction_plan.items()
            if key not in {"remove_fields", "delete_fields", "drop_fields"}
        }
    allowed_fields = set(tool_input.allowed_fields or updates.keys())
    protected_fields = protected_constraint_field_names(tool_input.evidence.hard_constraints)
    for field_name, value in updates.items():
        if field_name not in allowed_fields:
            continue
        canonical_field = canonical_constraint_field(field_name)
        if (
            field_name in protected_fields
            and not constraint_values_equal(value, tool_input.evidence.hard_constraints.get(canonical_field))
        ):
            continue
        plan[field_name] = value


def _requested_remove_fields(correction_plan: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for key in ("remove_fields", "delete_fields", "drop_fields"):
        fields.extend(string_list(correction_plan.get(key)))
    return unique_text(fields, limit=24)


def _hygiene_removed_items(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    removed: list[str] = []
    for field_name in ("categories", "keywords", "category_hints", "excluded_keywords"):
        before_values = set(string_list(before.get(field_name)))
        after_values = set(string_list(after.get(field_name)))
        for value in sorted(before_values - after_values):
            removed.append(f"hygiene_removed:{field_name}:{value}")
    if before.get("exact_title") and not after.get("exact_title"):
        removed.append("hygiene_removed:exact_title")
    return removed


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    fields = sorted(set(before) | set(after))
    return [field for field in fields if before.get(field) != after.get(field)]


def _preserved_constraints(evidence: SelfCorrectionEvidence) -> list[str]:
    return [f"{key}={value}" for key, value in evidence.hard_constraints.items()]

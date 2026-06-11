# 中文注释：实现 Agent 自校正证据收集和硬约束守卫。

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.agent.list_utils import string_list, unique_text
from app.services.agent.planning.query_plan_constraints import (
    canonical_constraint_field,
    constraint_value_from_mapping,
    constraint_values_equal,
    has_constraint_value,
    is_empty_constraint_value,
    protected_constraint_field_names,
)
from app.services.agent.self_correction.self_correction_evidence import (
    SelfCorrectionEvidence,
)
from app.services.agent.self_correction.self_correction_schema import LLMSelfCorrectionReviewResult

GuardRepairAction = Literal["allow", "strip_unsafe_changes", "block"]
_CORE_TERM_FIELDS = ("keywords", "core_terms", "recall_expansion_terms", "category_hints")
_REMOVE_FIELD_KEYS = ("remove_fields", "delete_fields", "drop_fields")


class HardConstraintGuardResult(BaseModel):
    passed: bool
    rejected_changes: list[str] = Field(default_factory=list)
    safe_correction_plan: dict[str, Any] = Field(default_factory=dict)
    repair_action: GuardRepairAction = "allow"


def guard_self_correction_plan(
    *,
    evidence: SelfCorrectionEvidence,
    review_result: LLMSelfCorrectionReviewResult,
) -> HardConstraintGuardResult:
    correction_plan = deepcopy(review_result.correction_plan or {})
    rejected: list[str] = []
    rejected.extend(_hard_constraint_removal_violations(correction_plan, evidence))
    rejected.extend(_hard_constraint_value_violations(correction_plan, evidence))
    if rejected:
        return HardConstraintGuardResult(
            passed=False,
            rejected_changes=unique_text(rejected, limit=24),
            safe_correction_plan={},
            repair_action="block",
        )
    stripped = _strip_non_primary_titles(correction_plan, evidence)
    if stripped:
        return HardConstraintGuardResult(
            passed=True,
            rejected_changes=unique_text(stripped, limit=24),
            safe_correction_plan=correction_plan,
            repair_action="strip_unsafe_changes",
        )
    return HardConstraintGuardResult(
        passed=True,
        rejected_changes=[],
        safe_correction_plan=correction_plan,
        repair_action="allow",
    )


def _hard_constraint_removal_violations(
    correction_plan: dict[str, Any],
    evidence: SelfCorrectionEvidence,
) -> list[str]:
    violations: list[str] = []
    hard_fields = protected_constraint_field_names(evidence.hard_constraints)
    for key in _REMOVE_FIELD_KEYS:
        for field in string_list(correction_plan.get(key)):
            if field in hard_fields:
                violations.append(f"cannot_remove_hard_constraint:{canonical_constraint_field(field)}")
    return violations


def _hard_constraint_value_violations(
    correction_plan: dict[str, Any],
    evidence: SelfCorrectionEvidence,
) -> list[str]:
    proposed_plan = correction_plan.get("query_plan")
    if not isinstance(proposed_plan, dict):
        proposed_plan = correction_plan
    violations: list[str] = []
    for field in evidence.hard_constraints:
        if not has_constraint_value(proposed_plan, field):
            continue
        original = evidence.hard_constraints[field]
        proposed = constraint_value_from_mapping(field, proposed_plan)
        if is_empty_constraint_value(proposed):
            violations.append(f"cannot_clear_hard_constraint:{field}")
        elif not constraint_values_equal(proposed, original):
            violations.append(f"cannot_change_hard_constraint:{field}")
    return violations


def _strip_non_primary_titles(
    correction_plan: dict[str, Any],
    evidence: SelfCorrectionEvidence,
) -> list[str]:
    unsafe_titles = {
        _norm_title(item.title)
        for item in evidence.candidate_snapshot
        if item.fit_type in {"support_context", "off_scope", "uncertain"}
    }
    unsafe_titles.discard("")
    if not unsafe_titles:
        return []
    stripped: list[str] = []
    containers = [correction_plan]
    if isinstance(correction_plan.get("query_plan"), dict):
        containers.append(correction_plan["query_plan"])
    for container in containers:
        for field in _CORE_TERM_FIELDS:
            values = string_list(container.get(field))
            if not values:
                continue
            kept = []
            for value in values:
                if _norm_title(value) in unsafe_titles:
                    stripped.append(f"removed_non_primary_title_from_{field}:{value}")
                    continue
                kept.append(value)
            container[field] = kept
    return stripped


def _norm_title(value: object) -> str:
    return " ".join(str(value or "").lower().split())

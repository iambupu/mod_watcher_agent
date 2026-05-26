from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.agent.planning.fallback_query_plan import build_fallback_query_plan
from app.services.agent.planning.query_diagnosis import diagnose_query
from app.services.agent.planning.tool_planner import build_tool_plan
from app.services.agent.quality._checks import (
    exception_check,
    invalid_expect_field_types,
    load_case_objects,
)
from app.services.agent.quality._checks import (
    expect_field_type_summary as build_expect_field_type_summary,
)
from app.services.agent.query_planner import normalize_query_plan

_EXPECT_FIELD_TYPES = {
    "adult_content": "bool",
    "author": "string",
    "categories": "list",
    "compatibility_terms": "list",
    "context_inherit_score_max": "number",
    "context_inherit_score_min": "number",
    "created_after": "string",
    "created_before": "string",
    "diagnosis_intent": "string",
    "diagnosis_missing_slots": "list",
    "diagnosis_preference_memory_age_days": "number",
    "diagnosis_preference_memory_applied": "bool",
    "diagnosis_preference_memory_reason": "string",
    "diagnosis_preference_memory_stale": "bool",
    "diagnosis_should_clarify": "bool",
    "exact_title": "string",
    "excluded_keywords": "list",
    "excluded_sources": "list",
    "excluded_summary_languages": "list",
    "external_id": "string",
    "game_domains": "list",
    "games": "list",
    "has_thumbnail": "bool",
    "intent": "string",
    "min_downloads": "number",
    "min_endorsements": "number",
    "min_likes": "number",
    "min_views": "number",
    "published_after": "string",
    "published_before": "string",
    "required_terms": "list",
    "requirement_terms": "list",
    "should_use_context": "bool",
    "sort_field": "string",
    "source_url": "string",
    "sources": "list",
    "summary_languages": "list",
    "tags": "list",
    "tools": "list",
    "topic_shift_detected": "bool",
    "understanding_field_contains": "object",
    "understanding_field_not_contains": "object",
    "updated_after": "string",
    "updated_before": "string",
    "updated_since_days": "number",
    "version": "string_or_null",
}


def load_quality_cases(path: Path) -> list[dict[str, Any]]:
    return load_case_objects(path, label="quality")


def supported_expect_fields() -> list[str]:
    return sorted(_EXPECT_FIELD_TYPES)


def expect_field_type_summary() -> dict[str, str]:
    return build_expect_field_type_summary(_EXPECT_FIELD_TYPES)


def run_quality_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    failed = 0
    failed_case_ids: list[str] = []
    case_results: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id") or "<unknown>")
        try:
            passed, checks = _case_passes(case)
        except Exception as exc:
            passed = False
            checks = [exception_check(exc)]
        case_results.append(
            {
                "id": case_id,
                "passed": passed,
                "checks": checks,
            }
        )
        if not passed:
            failed += 1
            failed_case_ids.append(case_id)
    total = len(cases)
    passed_count = total - failed
    return {
        "total": total,
        "passed": passed_count,
        "failed": failed,
        "failed_case_ids": failed_case_ids,
        "analysis": {
            "suite": "agent_quality_core",
            "total_cases": total,
            "pass_rate": round((passed_count / total), 3) if total else 1.0,
        },
        "evidence": {
            "case_results": case_results,
        },
        "conclusion": {
            "status": "passed" if failed == 0 else "failed",
            "ready_for_regression_gate": failed == 0,
        },
    }


def _case_passes(case: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    query = str(case.get("query") or "")
    expected = case.get("expect") if isinstance(case.get("expect"), dict) else {}
    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, *, actual: Any = None, expected_value: Any = None) -> bool:
        checks.append(
            {
                "name": name,
                "passed": bool(condition),
                "actual": actual,
                "expected": expected_value,
            }
        )
        return bool(condition)

    unknown_expect_fields = sorted(set(expected) - set(_EXPECT_FIELD_TYPES))
    if unknown_expect_fields:
        check(
            "case.expect.supported_fields",
            False,
            actual=unknown_expect_fields,
            expected_value=supported_expect_fields(),
        )
        return False, checks
    invalid_expect_types = invalid_expect_field_types(expected, _EXPECT_FIELD_TYPES)
    if invalid_expect_types:
        check(
            "case.expect.field_types",
            False,
            actual=invalid_expect_types,
            expected_value=expect_field_type_summary(),
        )
        return False, checks

    plan = build_fallback_query_plan(query)
    if isinstance(case.get("slot_options"), dict):
        plan = normalize_query_plan(plan, query, _quality_slot_options(case["slot_options"]))
    if "intent" in expected and not check("plan.intent", plan.get("intent") == expected["intent"], actual=plan.get("intent"), expected_value=expected["intent"]):
        return False, checks
    if "adult_content" in expected and not check(
        "plan.adult_content",
        plan.get("adult_content") == expected["adult_content"],
        actual=plan.get("adult_content"),
        expected_value=expected["adult_content"],
    ):
        return False, checks
    if "sort_field" in expected and not check("plan.sort_field", plan.get("sort_field") == expected["sort_field"], actual=plan.get("sort_field"), expected_value=expected["sort_field"]):
        return False, checks
    for key in ["min_downloads", "min_endorsements", "min_views", "min_likes"]:
        if key in expected and not check(f"plan.{key}", plan.get(key) == expected[key], actual=plan.get(key), expected_value=expected[key]):
            return False, checks
    if "updated_since_days" in expected and not check(
        "plan.updated_since_days",
        plan.get("updated_since_days") == expected["updated_since_days"],
        actual=plan.get("updated_since_days"),
        expected_value=expected["updated_since_days"],
    ):
        return False, checks
    for key in ["updated_after", "updated_before", "published_after", "published_before", "created_after", "created_before"]:
        if key in expected and not check(f"plan.{key}", plan.get(key) == expected[key], actual=plan.get(key), expected_value=expected[key]):
            return False, checks
    for key in [
        "games",
        "game_domains",
        "tags",
        "categories",
        "summary_languages",
        "excluded_summary_languages",
        "requirement_terms",
        "compatibility_terms",
    ]:
        if key in expected and not check(f"plan.{key}", (plan.get(key) or []) == expected[key], actual=(plan.get(key) or []), expected_value=expected[key]):
            return False, checks
    if "has_thumbnail" in expected and not check("plan.has_thumbnail", plan.get("has_thumbnail") == expected["has_thumbnail"], actual=plan.get("has_thumbnail"), expected_value=expected["has_thumbnail"]):
        return False, checks
    if "exact_title" in expected and not check("plan.exact_title", plan.get("exact_title") == expected["exact_title"], actual=plan.get("exact_title"), expected_value=expected["exact_title"]):
        return False, checks
    if "version" in expected and not check("plan.version", plan.get("version") == expected["version"], actual=plan.get("version"), expected_value=expected["version"]):
        return False, checks
    if "external_id" in expected and not check("plan.external_id", plan.get("external_id") == expected["external_id"], actual=plan.get("external_id"), expected_value=expected["external_id"]):
        return False, checks
    if "source_url" in expected and not check("plan.source_url", plan.get("source_url") == expected["source_url"], actual=plan.get("source_url"), expected_value=expected["source_url"]):
        return False, checks
    if "sources" in expected and not check("plan.sources", plan.get("sources") == expected["sources"], actual=plan.get("sources"), expected_value=expected["sources"]):
        return False, checks
    if "excluded_sources" in expected and not check("plan.excluded_sources", (plan.get("excluded_sources") or []) == expected["excluded_sources"], actual=(plan.get("excluded_sources") or []), expected_value=expected["excluded_sources"]):
        return False, checks
    if "author" in expected and not check("plan.author", plan.get("author") == expected["author"], actual=plan.get("author"), expected_value=expected["author"]):
        return False, checks
    if "excluded_keywords" in expected and not check("plan.excluded_keywords", (plan.get("excluded_keywords") or []) == expected["excluded_keywords"], actual=(plan.get("excluded_keywords") or []), expected_value=expected["excluded_keywords"]):
        return False, checks
    if "required_terms" in expected:
        text = query.lower()
        ok = all(str(term).lower() in text for term in expected["required_terms"])
        if not check("query.required_terms", ok, actual=query, expected_value=expected["required_terms"]):
            return False, checks
    if expected.get("should_use_context") and not check("context.required", bool(case.get("context")), actual=bool(case.get("context")), expected_value=True):
        return False, checks
    if "tools" in expected:
        tool_plan = build_tool_plan(query_diagnosis={"known_slots": {}}, preferences={}, capabilities={}, local_only=False)
        planned_tools = [step["tool"] for step in tool_plan["steps"]]
        ok = not any(tool not in planned_tools for tool in expected["tools"])
        if not check("tool_plan.required_tools", ok, actual=planned_tools, expected_value=expected["tools"]):
            return False, checks
    plan = _with_quality_evidence_id(plan)
    diagnosis_ok, diagnosis_checks = _diagnosis_expectations_pass(query, plan, case, expected)
    checks.extend(diagnosis_checks)
    if not diagnosis_ok:
        return False, checks
    return True, checks


def _diagnosis_expectations_pass(
    query: str,
    plan: dict[str, Any],
    case: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, *, actual: Any = None, expected_value: Any = None) -> bool:
        checks.append(
            {
                "name": name,
                "passed": bool(condition),
                "actual": actual,
                "expected": expected_value,
            }
        )
        return bool(condition)

    diagnosis = diagnose_query(
        query=query,
        query_plan=plan,
        active_constraints=case.get("context") if isinstance(case.get("context"), dict) else {},
        preferences=case.get("preferences") if isinstance(case.get("preferences"), dict) else {},
        context_keywords=_string_list(case.get("context_keywords")),
        context_slots=case.get("context_slots") if isinstance(case.get("context_slots"), dict) else {},
    )
    understanding = diagnosis.get("understanding") if isinstance(diagnosis.get("understanding"), dict) else {}
    evidence = understanding.get("evidence") if isinstance(understanding.get("evidence"), list) else []
    if not check(
        "diagnosis.understanding_shape",
        isinstance(understanding.get("intent"), str)
        and isinstance(understanding.get("slots"), dict)
        and isinstance(understanding.get("confidence"), float | int)
        and isinstance(evidence, list)
        and bool(evidence),
        actual=understanding,
        expected_value={"intent": "str", "slots": "dict", "confidence": "number", "evidence": "non_empty_list"},
    ):
        return False, checks
    evidence_id = str(plan.get("evidence_id") or "")
    if not check(
        "diagnosis.understanding_evidence_ids",
        bool(evidence_id) and all(isinstance(item, dict) and item.get("evidence_id") == evidence_id for item in evidence),
        actual=[item.get("evidence_id") for item in evidence if isinstance(item, dict)],
        expected_value=evidence_id,
    ):
        return False, checks
    evidence_map: dict[str, Any] = {}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        if field and field not in evidence_map:
            evidence_map[field] = item.get("value")
    for field, target in (expected.get("understanding_field_contains") or {}).items():
        actual = evidence_map.get(str(field))
        values = actual if isinstance(actual, list) else []
        if not check(
            f"diagnosis.understanding.{field}_contains",
            str(target) in [str(item) for item in values],
            actual=values,
            expected_value=target,
        ):
            return False, checks
    for field, target in (expected.get("understanding_field_not_contains") or {}).items():
        actual = evidence_map.get(str(field))
        values = actual if isinstance(actual, list) else []
        if not check(
            f"diagnosis.understanding.{field}_not_contains",
            str(target) not in [str(item) for item in values],
            actual=values,
            expected_value=f"not {target}",
        ):
            return False, checks
    if "diagnosis_intent" in expected and not check(
        "diagnosis.intent",
        diagnosis.get("intent") == expected["diagnosis_intent"],
        actual=diagnosis.get("intent"),
        expected_value=expected["diagnosis_intent"],
    ):
        return False, checks
    if "diagnosis_should_clarify" in expected and not check(
        "diagnosis.should_clarify",
        bool(diagnosis.get("should_clarify")) == bool(expected["diagnosis_should_clarify"]),
        actual=bool(diagnosis.get("should_clarify")),
        expected_value=bool(expected["diagnosis_should_clarify"]),
    ):
        return False, checks
    if "diagnosis_missing_slots" in expected and not check(
        "diagnosis.missing_slots",
        list(diagnosis.get("missing_slots") or []) == list(expected["diagnosis_missing_slots"]),
        actual=list(diagnosis.get("missing_slots") or []),
        expected_value=list(expected["diagnosis_missing_slots"]),
    ):
        return False, checks
    topic_shift = _evidence_field_value(evidence, "topic_shift_detected")
    if "topic_shift_detected" in expected and not check(
        "diagnosis.topic_shift_detected",
        bool(topic_shift) == bool(expected["topic_shift_detected"]),
        actual=bool(topic_shift),
        expected_value=bool(expected["topic_shift_detected"]),
    ):
        return False, checks
    inherit_score = _evidence_field_value(evidence, "context_inherit_score")
    try:
        inherit_score_value = float(inherit_score) if inherit_score is not None else None
    except (TypeError, ValueError):
        inherit_score_value = None
    if "context_inherit_score_min" in expected:
        ok = inherit_score_value is not None and inherit_score_value >= float(expected["context_inherit_score_min"])
        if not check(
            "diagnosis.context_inherit_score_min",
            ok,
            actual=inherit_score_value,
            expected_value=float(expected["context_inherit_score_min"]),
        ):
            return False, checks
    if "context_inherit_score_max" in expected:
        ok = inherit_score_value is not None and inherit_score_value <= float(expected["context_inherit_score_max"])
        if not check(
            "diagnosis.context_inherit_score_max",
            ok,
            actual=inherit_score_value,
            expected_value=float(expected["context_inherit_score_max"]),
        ):
            return False, checks
    pref_reason = _evidence_field_value(evidence, "preference_memory_reason")
    if "diagnosis_preference_memory_reason" in expected and not check(
        "diagnosis.preference_memory_reason",
        str(pref_reason or "") == str(expected["diagnosis_preference_memory_reason"]),
        actual=str(pref_reason or ""),
        expected_value=str(expected["diagnosis_preference_memory_reason"]),
    ):
        return False, checks
    pref_applied = _evidence_field_value(evidence, "preference_memory_applied")
    if "diagnosis_preference_memory_applied" in expected and not check(
        "diagnosis.preference_memory_applied",
        bool(pref_applied) == bool(expected["diagnosis_preference_memory_applied"]),
        actual=bool(pref_applied),
        expected_value=bool(expected["diagnosis_preference_memory_applied"]),
    ):
        return False, checks
    pref_stale = _evidence_field_value(evidence, "preference_memory_stale")
    if "diagnosis_preference_memory_stale" in expected and not check(
        "diagnosis.preference_memory_stale",
        bool(pref_stale) == bool(expected["diagnosis_preference_memory_stale"]),
        actual=bool(pref_stale),
        expected_value=bool(expected["diagnosis_preference_memory_stale"]),
    ):
        return False, checks
    pref_age = _evidence_field_value(evidence, "preference_memory_age_days")
    if "diagnosis_preference_memory_age_days" in expected and not check(
        "diagnosis.preference_memory_age_days",
        int(pref_age or 0) == int(expected["diagnosis_preference_memory_age_days"]),
        actual=int(pref_age or 0),
        expected_value=int(expected["diagnosis_preference_memory_age_days"]),
    ):
        return False, checks
    return True, checks


def _evidence_field_value(evidence: list[dict[str, Any]], field: str) -> Any:
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if str(item.get("field") or "").strip() == field:
            return item.get("value")
    return None


def _with_quality_evidence_id(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("evidence_id"):
        return plan
    updated = dict(plan)
    updated["evidence_id"] = f"ev_quality_{uuid4().hex[:12]}"
    return updated


def _quality_slot_options(raw: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "games": _string_list(raw.get("games")),
        "game_domains": _string_list(raw.get("game_domains")),
        "categories": _string_list(raw.get("categories")),
        "sources": _string_list(raw.get("sources")),
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list | tuple | set):
        values = list(value)
    else:
        values = []
    return [str(item).strip() for item in values if str(item).strip()]

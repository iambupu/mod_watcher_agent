import json
import logging
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.main as main_module
from app.db import get_session
from app.main import app as fastapi_app
from app.models.mod import Mod
from app.models.settings import Setting
from app.services import llm_provider_config as llm_provider_config_module
from app.services.agent import rate_limiter as rate_limiter_module
from app.services.agent.quality._checks import (
    exception_check,
    invalid_expect_field_types,
    load_case_objects,
)
from app.services.agent.quality._checks import (
    expect_field_type_summary as build_expect_field_type_summary,
)
from app.services.agent.search_types import SearchResult
from app.services.agent.tools.loverslab_google_search_tool import LoversLabGoogleSearchTool
from app.services.agent.tools.loverslab_search_scrape_tool import LoversLabSearchScrapeTool
from app.services.agent.tools.nexusmods_search_tool import NexusModsSearchTool
from app.utils.numeric import is_plain_int, safe_nonnegative_int, safe_optional_float

_EXPECT_FIELD_TYPES = {
    "answer_contains": "string",
    "answer_not_contains": "string",
    "audit_analysis_contains": "object",
    "audit_analysis_equals": "object",
    "audit_conclusion_equals": "object",
    "audit_retrieval_decision_contains": "object",
    "audit_retrieval_decision_not_contains": "object",
    "audit_semantic_trace_contains": "object",
    "audit_semantic_trace_not_contains": "object",
    "audit_web_search_contains": "object",
    "audit_web_search_equals": "object",
    "clarifying_question_contains": "string",
    "context_inherit_score_min": "number",
    "exclude_titles": "list",
    "log_contains": "list",
    "memory_field_equals": "object",
    "memory_field_min": "object",
    "retrieval_evidence_contains": "object",
    "result_sources": "list",
    "response_card_contains": "object",
    "slot_game": "string",
    "top_source": "string",
    "top_title": "string",
    "topic_shift_detected": "bool",
    "understanding_field_contains": "object",
    "understanding_field_equals": "object",
    "understanding_field_max": "object",
    "understanding_field_min": "object",
    "understanding_field_not_contains": "object",
}


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def load_e2e_quality_cases(path: Path) -> list[dict[str, Any]]:
    return load_case_objects(path, label="e2e quality")


def supported_expect_fields() -> list[str]:
    return sorted(_EXPECT_FIELD_TYPES)


def expect_field_type_summary() -> dict[str, str]:
    return build_expect_field_type_summary(_EXPECT_FIELD_TYPES)


def run_e2e_quality_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    case_results: list[dict[str, Any]] = []
    failed_case_ids: list[str] = []
    for case in cases:
        case_id = str(case.get("id") or "<unknown>")
        try:
            passed, checks = _run_single_case(case, fast_mode=True)
        except Exception as exc:
            passed = False
            checks = [exception_check(exc)]
        case_results.append({"id": case_id, "passed": passed, "checks": checks})
        if not passed:
            failed_case_ids.append(case_id)
    total = len(cases)
    failed = len(failed_case_ids)
    passed_count = total - failed
    return {
        "total": total,
        "passed": passed_count,
        "failed": failed,
        "failed_case_ids": failed_case_ids,
        "analysis": {
            "suite": "agent_chat_e2e_quality",
            "total_cases": total,
            "pass_rate": round((passed_count / total), 3) if total else 1.0,
        },
        "evidence": {"case_results": case_results},
        "conclusion": {
            "status": "passed" if failed == 0 else "failed",
            "ready_for_regression_gate": failed == 0,
        },
    }


def _run_single_case(case: dict[str, Any], *, fast_mode: bool) -> tuple[bool, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, *, actual: Any = None, expected: Any = None) -> bool:
        checks.append({"name": name, "passed": bool(condition), "actual": actual, "expected": expected})
        return bool(condition)

    expected = case.get("expect") if isinstance(case.get("expect"), dict) else {}
    unknown_expect_fields = sorted(set(expected) - set(_EXPECT_FIELD_TYPES))
    if unknown_expect_fields:
        check(
            "case.expect.supported_fields",
            False,
            actual=unknown_expect_fields,
            expected=supported_expect_fields(),
        )
        return False, checks
    invalid_expect_types = invalid_expect_field_types(expected, _EXPECT_FIELD_TYPES)
    if invalid_expect_types:
        check(
            "case.expect.field_types",
            False,
            actual=invalid_expect_types,
            expected=expect_field_type_summary(),
        )
        return False, checks

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    _seed_default_mods(engine)
    _seed_case_mods(engine, case)

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    log_handler = _ListHandler()
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)
    original_setup_scheduler = main_module.setup_scheduler
    original_init_db = main_module.init_db
    original_deferred_startup_maintenance = main_module._run_deferred_startup_maintenance
    original_engine = main_module.engine
    original_provider_has_credentials = llm_provider_config_module.provider_has_credentials
    original_enforce_rate_limit = rate_limiter_module.enforce_rate_limit
    original_nexus_run = NexusModsSearchTool.run
    original_loverslab_google_run = LoversLabGoogleSearchTool.run
    original_loverslab_scrape_run = LoversLabSearchScrapeTool.run
    if fast_mode:
        async def _noop_setup_scheduler(_session: Any | None = None) -> None:
            return None

        def _noop_init_db() -> None:
            return None

        async def _noop_deferred_startup_maintenance() -> None:
            return None

        async def _noop_enforce_rate_limit(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
            return None

        stub_online_results = case.get("stub_online_results") if isinstance(case.get("stub_online_results"), dict) else {}

        async def _empty_leaf_search(self: Any, tool_input: Any) -> list[Any]:  # noqa: ARG001
            self.last_status = "succeeded"
            self.last_reason = None
            return []

        async def _stubbed_leaf_search(self: Any, tool_input: Any) -> list[Any]:  # noqa: ARG001
            tool_results = stub_online_results.get(str(getattr(self, "name", "") or ""))
            if not isinstance(tool_results, list):
                return await _empty_leaf_search(self, tool_input)
            self.last_status = "succeeded"
            self.last_reason = None
            return [
                SearchResult(
                    score=_stub_search_score(item),
                    mod=_mod_from_stub(item),
                    tool_name=str(getattr(self, "name", "")),
                )
                for item in tool_results
                if isinstance(item, dict)
            ]

        main_module.setup_scheduler = _noop_setup_scheduler
        main_module.init_db = _noop_init_db
        main_module._run_deferred_startup_maintenance = _noop_deferred_startup_maintenance
        main_module.engine = engine
        llm_provider_config_module.provider_has_credentials = lambda provider, api_key: False  # noqa: ARG005
        rate_limiter_module.enforce_rate_limit = _noop_enforce_rate_limit
        NexusModsSearchTool.run = _stubbed_leaf_search
        LoversLabGoogleSearchTool.run = _stubbed_leaf_search
        LoversLabSearchScrapeTool.run = _stubbed_leaf_search
    try:
        with TestClient(fastapi_app) as client:
            response = None
            for index, turn in enumerate(_case_turns(case), start=1):
                payload = {
                    "message": str(turn.get("message") or ""),
                    "history": list(turn.get("history") or []),
                }
                response = client.post("/api/agent/chat", json=payload)
                if not check(
                    f"http.status.turn_{index}",
                    response.status_code == 200,
                    actual=response.status_code,
                    expected=200,
                ):
                    return False, checks
            if response is None:
                check("case.turns", False, actual=None, expected="at least one turn")
                return False, checks
        if not check("http.status", response.status_code == 200, actual=response.status_code, expected=200):
            return False, checks
        body = response.json()
        if not check(
            "response.audit_shape",
            isinstance(body.get("audit"), dict)
            and all(key in (body.get("audit") or {}) for key in ("analysis", "evidence", "conclusion")),
            actual=list((body.get("audit") or {}).keys()) if isinstance(body.get("audit"), dict) else None,
            expected=["analysis", "evidence", "conclusion"],
        ):
            return False, checks
        audit = body.get("audit") if isinstance(body.get("audit"), dict) else {}
        if not check(
            "response.audit.analysis_evidence_conclusion_order",
            _mapping_has_standard_order(audit),
            actual=list(audit.keys())[:3] if isinstance(audit, dict) else None,
            expected=["analysis", "evidence", "conclusion"],
        ):
            return False, checks
        for section_name in ["analysis", "evidence", "conclusion"]:
            section = audit.get(section_name) if isinstance(audit, dict) else None
            if not check(
                f"response.audit.{section_name}_non_empty",
                isinstance(section, dict) and bool(section),
                actual=section,
                expected="non-empty object",
            ):
                return False, checks
        if not check(
            "response.evidence_id_shape",
            isinstance(body.get("evidence_id"), str) and str(body.get("evidence_id")).startswith("ev_"),
            actual=body.get("evidence_id"),
            expected="ev_*",
        ):
            return False, checks
        matches = body.get("matches") if isinstance(body.get("matches"), list) else []
        response_cards = body.get("response_cards") if isinstance(body.get("response_cards"), dict) else {}
        if not check(
            "response.cards.analysis_evidence_conclusion_order",
            _response_cards_have_standard_order(response_cards),
            actual=list(response_cards.keys())[:3] if isinstance(response_cards, dict) else None,
            expected=["analysis", "evidence", "conclusion"],
        ):
            return False, checks
        for card_name in ["analysis", "evidence", "conclusion"]:
            items = response_cards.get(card_name) if isinstance(response_cards, dict) else None
            if not check(
                f"response.cards.{card_name}_non_empty",
                isinstance(items, list) and all(isinstance(item, str) and item.strip() for item in items) and bool(items),
                actual=items,
                expected="non-empty list[str]",
            ):
                return False, checks
        titles = [str(item.get("title") or "") for item in matches if isinstance(item, dict)]
        sources = [str(item.get("source") or "") for item in matches if isinstance(item, dict)]
        if "top_title" in expected and not check(
            "result.top_title",
            bool(titles) and titles[0] == str(expected["top_title"]),
            actual=titles[0] if titles else None,
            expected=expected["top_title"],
        ):
            return False, checks
        for excluded in expected.get("exclude_titles") or []:
            if not check(
                f"result.exclude_title:{excluded}",
                str(excluded) not in titles,
                actual=titles,
                expected=f"exclude {excluded}",
            ):
                return False, checks
        if "top_source" in expected and not check(
            "result.top_source",
            bool(sources) and sources[0] == str(expected["top_source"]),
            actual=sources[0] if sources else None,
            expected=expected["top_source"],
        ):
            return False, checks
        if "result_sources" in expected:
            expected_sources = [str(item) for item in expected["result_sources"]]
            actual_sources = sorted({source for source in sources if source})
            if not check(
                "result.sources",
                actual_sources == sorted(expected_sources),
                actual=actual_sources,
                expected=sorted(expected_sources),
            ):
                return False, checks
        if "answer_contains" in expected:
            answer = str(body.get("answer") or "")
            target = str(expected["answer_contains"])
            if not check("response.answer_contains", target in answer, actual=answer, expected=target):
                return False, checks
        if "answer_not_contains" in expected:
            answer = str(body.get("answer") or "")
            target = str(expected["answer_not_contains"])
            if not check("response.answer_not_contains", target not in answer, actual=answer, expected=f"not {target}"):
                return False, checks
        for section, target in (expected.get("response_card_contains") or {}).items():
            items = response_cards.get(str(section)) if isinstance(response_cards, dict) else None
            values = items if isinstance(items, list) else []
            if not check(
                f"response.cards.{section}_contains",
                any(str(target) in str(item) for item in values),
                actual=values,
                expected=target,
            ):
                return False, checks
        understanding = body.get("understanding") if isinstance(body.get("understanding"), dict) else {}
        slots = understanding.get("slots") if isinstance(understanding.get("slots"), dict) else {}
        if "slot_game" in expected and not check(
            "understanding.slot_game",
            str(slots.get("game") or "") == str(expected["slot_game"]),
            actual=slots.get("game"),
            expected=expected["slot_game"],
        ):
            return False, checks
        evidence = understanding.get("evidence") if isinstance(understanding.get("evidence"), list) else []
        evidence_map: dict[str, Any] = {}
        for item in evidence:
            if isinstance(item, dict):
                field = str(item.get("field") or "").strip()
                if field and field not in evidence_map:
                    evidence_map[field] = item.get("value")
        for field, target in (expected.get("understanding_field_equals") or {}).items():
            if not check(
                f"understanding.{field}",
                evidence_map.get(str(field)) == target,
                actual=evidence_map.get(str(field)),
                expected=target,
            ):
                return False, checks
        for field, target in (expected.get("understanding_field_not_contains") or {}).items():
            actual = evidence_map.get(str(field))
            values = actual if isinstance(actual, list) else []
            if not check(
                f"understanding.{field}_not_contains",
                str(target) not in [str(item) for item in values],
                actual=values,
                expected=f"not {target}",
            ):
                return False, checks
        for field, target in (expected.get("understanding_field_contains") or {}).items():
            actual = evidence_map.get(str(field))
            values = actual if isinstance(actual, list) else []
            if not check(
                f"understanding.{field}_contains",
                str(target) in [str(item) for item in values],
                actual=values,
                expected=target,
            ):
                return False, checks
        for field, target in (expected.get("understanding_field_min") or {}).items():
            actual = safe_optional_float(evidence_map.get(str(field)))
            min_target = safe_optional_float(target)
            if not check(
                f"understanding.{field}_min",
                actual is not None and min_target is not None and actual >= min_target,
                actual=actual,
                expected=min_target,
            ):
                return False, checks
        for field, target in (expected.get("understanding_field_max") or {}).items():
            actual = safe_optional_float(evidence_map.get(str(field)))
            max_target = safe_optional_float(target)
            if not check(
                f"understanding.{field}_max",
                actual is not None and max_target is not None and actual <= max_target,
                actual=actual,
                expected=max_target,
            ):
                return False, checks
        if "topic_shift_detected" in expected and not check(
            "understanding.topic_shift_detected",
            bool(evidence_map.get("topic_shift_detected")) == bool(expected["topic_shift_detected"]),
            actual=bool(evidence_map.get("topic_shift_detected")),
            expected=bool(expected["topic_shift_detected"]),
        ):
            return False, checks
        if "context_inherit_score_min" in expected:
            actual = safe_optional_float(evidence_map.get("context_inherit_score"))
            target = float(expected["context_inherit_score_min"])
            if not check("understanding.context_inherit_score_min", actual is not None and actual >= target, actual=actual, expected=target):
                return False, checks
        memory_evidence = body.get("memory_evidence") if isinstance(body.get("memory_evidence"), list) else []
        memory_map: dict[str, Any] = {}
        for item in memory_evidence:
            if isinstance(item, dict):
                field = str(item.get("field") or "").strip()
                if field and field not in memory_map:
                    memory_map[field] = item.get("value")
        for field, target in (expected.get("memory_field_equals") or {}).items():
            if not check(
                f"memory.{field}",
                memory_map.get(str(field)) == target,
                actual=memory_map.get(str(field)),
                expected=target,
            ):
                return False, checks
        for field, target in (expected.get("memory_field_min") or {}).items():
            actual = safe_optional_float(memory_map.get(str(field)))
            min_target = safe_optional_float(target)
            if not check(
                f"memory.{field}_min",
                actual is not None and min_target is not None and actual >= min_target,
                actual=actual,
                expected=min_target,
            ):
                return False, checks
        retrieval_evidence = body.get("retrieval_evidence") if isinstance(body.get("retrieval_evidence"), list) else []
        for field, target in (expected.get("retrieval_evidence_contains") or {}).items():
            if not check(
                f"retrieval_evidence.{field}_contains",
                _items_contain_field_value(retrieval_evidence, str(field), target),
                actual=[
                    item.get(str(field))
                    for item in retrieval_evidence
                    if isinstance(item, dict) and str(field) in item
                ],
                expected=target,
            ):
                return False, checks
        audit_evidence = audit.get("evidence") if isinstance(audit.get("evidence"), dict) else {}
        audit_analysis = audit.get("analysis") if isinstance(audit.get("analysis"), dict) else {}
        for field, target in (expected.get("audit_analysis_equals") or {}).items():
            if not check(
                f"audit.analysis.{field}",
                audit_analysis.get(str(field)) == target,
                actual=audit_analysis.get(str(field)),
                expected=target,
            ):
                return False, checks
        for field, target in (expected.get("audit_analysis_contains") or {}).items():
            actual = audit_analysis.get(str(field))
            values = actual if isinstance(actual, list) else []
            if not check(
                f"audit.analysis.{field}_contains",
                str(target) in [str(item) for item in values],
                actual=values,
                expected=target,
            ):
                return False, checks
        retrieval_decision = (
            audit_evidence.get("retrieval_decision")
            if isinstance(audit_evidence.get("retrieval_decision"), dict)
            else {}
        )
        if not check(
            "audit.evidence.retrieval_decision_shape",
            bool(retrieval_decision)
            and isinstance(retrieval_decision.get("mode"), str)
            and isinstance(retrieval_decision.get("reasons"), list)
            and isinstance(retrieval_decision.get("reason_groups"), dict),
            actual=retrieval_decision,
            expected={"mode": "str", "reasons": "list", "reason_groups": "dict"},
        ):
            return False, checks
        reason_groups = retrieval_decision.get("reason_groups") if isinstance(retrieval_decision.get("reason_groups"), dict) else {}
        if not check(
            "audit.evidence.retrieval_decision_reason_groups",
            all(isinstance(reason_groups.get(key), list) for key in ("context", "memory", "web", "semantic")),
            actual=reason_groups,
            expected={"context": "list", "memory": "list", "web": "list", "semantic": "list"},
        ):
            return False, checks
        for field, target in (expected.get("audit_retrieval_decision_contains") or {}).items():
            actual = retrieval_decision.get(str(field))
            values = actual if isinstance(actual, list) else []
            if not check(
                f"audit.evidence.retrieval_decision.{field}_contains",
                str(target) in [str(item) for item in values],
                actual=values,
                expected=target,
            ):
                return False, checks
        for field, target in (expected.get("audit_retrieval_decision_not_contains") or {}).items():
            actual = retrieval_decision.get(str(field))
            values = actual if isinstance(actual, list) else []
            if not check(
                f"audit.evidence.retrieval_decision.{field}_not_contains",
                str(target) not in [str(item) for item in values],
                actual=values,
                expected=f"not {target}",
            ):
                return False, checks
        semantic_trace = audit_evidence.get("semantic_trace")
        if semantic_trace is not None:
            if not check(
                "audit.evidence.semantic_trace_shape",
                isinstance(semantic_trace, dict)
                and isinstance(semantic_trace.get("anchors"), list)
                and isinstance(semantic_trace.get("context_anchors"), list)
                and isinstance(semantic_trace.get("domains"), list)
                and is_plain_int(semantic_trace.get("inherited_anchor_overlap"))
                and is_plain_int(semantic_trace.get("memory_fragment_count")),
                actual=semantic_trace,
                expected={
                    "anchors": "list",
                    "context_anchors": "list",
                    "domains": "list",
                    "inherited_anchor_overlap": "int",
                    "memory_fragment_count": "int",
                },
            ):
                return False, checks
            for field, target in (expected.get("audit_semantic_trace_contains") or {}).items():
                actual = semantic_trace.get(str(field))
                values = actual if isinstance(actual, list) else []
                if not check(
                    f"audit.evidence.semantic_trace.{field}_contains",
                    str(target) in [str(item) for item in values],
                    actual=values,
                    expected=target,
                ):
                    return False, checks
            for field, target in (expected.get("audit_semantic_trace_not_contains") or {}).items():
                actual = semantic_trace.get(str(field))
                values = actual if isinstance(actual, list) else []
                if not check(
                    f"audit.evidence.semantic_trace.{field}_not_contains",
                    str(target) not in [str(item) for item in values],
                    actual=values,
                    expected=f"not {target}",
                ):
                    return False, checks
        web_search = audit_evidence.get("web_search")
        if web_search is not None:
            if not check(
                "audit.evidence.web_search_shape",
                isinstance(web_search, dict)
                and isinstance(web_search.get("enabled"), bool)
                and isinstance(web_search.get("queried"), bool)
                and isinstance(web_search.get("tools"), list)
                and isinstance(web_search.get("trigger_reasons"), list),
                actual=web_search,
                expected={"enabled": "bool", "queried": "bool", "tools": "list", "trigger_reasons": "list"},
            ):
                return False, checks
            for field, target in (expected.get("audit_web_search_equals") or {}).items():
                if not check(
                    f"audit.evidence.web_search.{field}",
                    web_search.get(str(field)) == target,
                    actual=web_search.get(str(field)),
                    expected=target,
                ):
                    return False, checks
            for field, target in (expected.get("audit_web_search_contains") or {}).items():
                actual = web_search.get(str(field))
                values = actual if isinstance(actual, list) else []
                if not check(
                    f"audit.evidence.web_search.{field}_contains",
                    str(target) in [str(item) for item in values],
                    actual=values,
                    expected=target,
                ):
                    return False, checks
        audit_conclusion = audit.get("conclusion") if isinstance(audit.get("conclusion"), dict) else {}
        for field, target in (expected.get("audit_conclusion_equals") or {}).items():
            if not check(
                f"audit.conclusion.{field}",
                audit_conclusion.get(str(field)) == target,
                actual=audit_conclusion.get(str(field)),
                expected=target,
            ):
                return False, checks
        if "clarifying_question_contains" in expected:
            clarifying = str(body.get("clarifying_question") or "")
            target = str(expected["clarifying_question_contains"])
            if not check(
                "response.clarifying_question_contains",
                target in clarifying,
                actual=clarifying,
                expected=target,
            ):
                return False, checks
        messages = log_handler.messages
        for target in expected.get("log_contains") or []:
            if not check(
                f"log.contains:{target}",
                any(str(target) in message for message in messages),
                actual=target,
                expected="log message contains target",
            ):
                return False, checks
        evidence_id = str(body.get("evidence_id") or "")
        for field_name, items in [
            ("understanding.evidence", evidence),
            ("memory_evidence", memory_evidence),
            ("retrieval_evidence", retrieval_evidence),
        ]:
            if not check(
                f"response.evidence_ids.{field_name}",
                all(isinstance(item, dict) and item.get("evidence_id") == evidence_id for item in items),
                actual=[item.get("evidence_id") for item in items if isinstance(item, dict)],
                expected=evidence_id,
            ):
                return False, checks
        for stage in [
            "load_state",
            "summarize_context",
            "diagnose_query",
            "plan_tools",
            "staged_retrieval",
            "rank_results",
            "generate_answer",
            "reflect",
            "persist_result",
        ]:
            if not check(
                f"log.stage.{stage}",
                any(f"agent.stage step={stage} status=succeeded" in message for message in messages),
                actual=f"stage={stage}",
                expected="succeeded",
            ):
                return False, checks
            if not check(
                f"log.stage.{stage}.evidence_id",
                any(
                    f"agent.stage step={stage} status=succeeded" in message
                    and f"evidence_id={evidence_id}" in message
                    for message in messages
                ),
                actual=f"stage={stage}, evidence_id={evidence_id}",
                expected="stage log contains response evidence_id",
            ):
                return False, checks
        if not check(
            "log.tool.chat_request_guard",
            any("agent.tool name=chat_request_guard status=passed" in message for message in messages),
            actual="tool=chat_request_guard",
            expected="passed",
        ):
            return False, checks
        for tool_name in [
            "context_summary",
            "semantic_signal_extractor",
            "memory_context_loader",
            "executor_query",
            "query_diagnosis",
            "tool_planner",
            "result_fusion_ranker",
            "match_materializer",
            "answer_generation",
            "response_card_builder",
            "chat_answer",
        ]:
            if not check(
                f"log.tool.{tool_name}",
                any(f"agent.tool name={tool_name} status=succeeded" in message for message in messages),
                actual=f"tool={tool_name}",
                expected="succeeded",
            ):
                return False, checks
        if not check(
            "log.tool.web_search",
            any("agent.tool name=web_search status=" in message for message in messages),
            actual="tool=web_search",
            expected="succeeded_or_skipped",
        ):
            return False, checks
        if not check(
            "log.tool.llm_candidate_validator",
            any("agent.tool name=llm_candidate_validator status=" in message for message in messages),
            actual="tool=llm_candidate_validator",
            expected="succeeded_or_skipped_or_degraded",
        ):
            return False, checks
        for tool_name in [
            "chat_request_guard",
            "context_summary",
            "memory_context_loader",
            "memory_writeback",
            "semantic_signal_extractor",
            "query_diagnosis",
            "tool_planner",
            "executor_query",
            "web_search",
            "result_fusion_ranker",
            "match_materializer",
            "llm_candidate_validator",
            "answer_generation",
            "response_card_builder",
            "chat_answer",
        ]:
            if not check(
                f"log.tool.{tool_name}.evidence_id",
                any(f"agent.tool name={tool_name} status=" in message and f"evidence_id={evidence_id}" in message for message in messages),
                actual=f"tool={tool_name}, evidence_id={evidence_id}",
                expected="tool log contains response evidence_id",
            ):
                return False, checks
        if not check(
            "log.retrieval.local.evidence_id",
            any(
                (
                    "agent.retrieval.fts status=" in message
                    or "agent.retrieval.sql status=" in message
                )
                and f"evidence_id={evidence_id}" in message
                for message in messages
            ),
            actual=f"local retrieval evidence_id={evidence_id}",
            expected="local retrieval log contains response evidence_id",
        ):
            return False, checks
    finally:
        if fast_mode:
            main_module.setup_scheduler = original_setup_scheduler
            main_module.init_db = original_init_db
            main_module._run_deferred_startup_maintenance = original_deferred_startup_maintenance
            main_module.engine = original_engine
            llm_provider_config_module.provider_has_credentials = original_provider_has_credentials
            rate_limiter_module.enforce_rate_limit = original_enforce_rate_limit
            NexusModsSearchTool.run = original_nexus_run
            LoversLabGoogleSearchTool.run = original_loverslab_google_run
            LoversLabSearchScrapeTool.run = original_loverslab_scrape_run
        root_logger.removeHandler(log_handler)
        fastapi_app.dependency_overrides.clear()
        SQLModel.metadata.drop_all(engine)
        engine.dispose()
    return True, checks


def _case_turns(case: dict[str, Any]) -> list[dict[str, Any]]:
    turns = case.get("turns")
    if isinstance(turns, list):
        return [turn for turn in turns if isinstance(turn, dict)]
    return [
        {
            "message": str(case.get("message") or ""),
            "history": list(case.get("history") or []),
        }
    ]


def _seed_default_mods(engine: Any) -> None:
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="bimbo-1",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Bimbo Body Morph",
                    url="https://example.com/bimbo",
                    category="Body",
                    original_summary="A bimbo transformation style preset.",
                    first_seen_at="2026-05-20T00:00:00+00:00",
                    last_seen_at="2026-05-20T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="armor-1",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Realistic Armor Overhaul",
                    url="https://example.com/armor",
                    category="Armor",
                    original_summary="A lore friendly armor replacement.",
                    first_seen_at="2026-05-19T00:00:00+00:00",
                    last_seen_at="2026-05-19T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()


def _seed_case_mods(engine: Any, case: dict[str, Any]) -> None:
    mods = case.get("seed_mods")
    if isinstance(mods, list):
        with Session(engine) as session:
            for item in mods:
                if not isinstance(item, dict):
                    continue
                payload = dict(item)
                payload.setdefault("first_seen_at", "2026-05-23T00:00:00+00:00")
                payload.setdefault("last_seen_at", "2026-05-23T00:00:00+00:00")
                session.add(Mod(**payload))
            session.commit()

    settings = case.get("seed_settings")
    if not isinstance(settings, list):
        return
    with Session(engine) as session:
        for item in settings:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            value = item.get("value")
            if not isinstance(value, str):
                value = json.dumps(value or {}, ensure_ascii=False)
            session.add(
                Setting(
                    key=key,
                    value=value,
                    updated_at=str(item.get("updated_at") or "2026-05-24T00:00:00+00:00"),
                )
            )
        session.commit()


def _mod_from_stub(item: dict[str, Any]) -> Mod:
    payload = dict(item)
    payload.pop("score", None)
    payload.setdefault("source", "nexusmods")
    payload.setdefault("external_id", f"stub-{str(payload.get('title') or 'online').lower().replace(' ', '-')}")
    payload.setdefault("game", "Skyrim Special Edition")
    payload.setdefault("game_domain", "skyrimspecialedition")
    payload.setdefault("url", "https://example.com/stub-online")
    payload.setdefault("category", "Gameplay")
    payload.setdefault("first_seen_at", "2026-05-24T00:00:00+00:00")
    payload.setdefault("last_seen_at", "2026-05-24T00:00:00+00:00")
    payload.setdefault("adult_content", False)
    return Mod(**payload)


def _items_contain_field_value(items: list[Any], field: str, target: Any) -> bool:
    for item in items:
        if not isinstance(item, dict) or field not in item:
            continue
        actual = item.get(field)
        if isinstance(actual, list):
            if str(target) in [str(value) for value in actual]:
                return True
            continue
        if actual == target or str(actual) == str(target):
            return True
    return False


def _stub_search_score(item: dict[str, Any]) -> int:
    if "score" not in item:
        return 9
    return safe_nonnegative_int(item.get("score"))


def _response_cards_have_standard_order(cards: dict[str, Any]) -> bool:
    return _mapping_has_standard_order(cards)


def _mapping_has_standard_order(cards: dict[str, Any]) -> bool:
    if not isinstance(cards, dict):
        return False
    return list(cards.keys())[:3] == ["analysis", "evidence", "conclusion"]

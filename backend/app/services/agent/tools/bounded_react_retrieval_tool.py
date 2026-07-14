"""受控 ReAct 检索补强模块。

该模块放在 staged_retrieval 与 rank_results 之间，用有限轮次的
「评估 -> 决策 -> 工具执行 -> 观察」补强检索结果。它不是开放式 Agent
循环：所有动作都受质量阈值、硬约束守卫、工具计划和轮次上限约束，避免
为了追求更多结果而放宽用户已经明确给出的来源、游戏、标题或 URL 限制。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlmodel import Session

from app.services.agent.filter_value_utils import url_without_query
from app.services.agent.list_utils import string_list, unique_text
from app.services.agent.planning.open_discovery_policy import is_open_discovery_plan
from app.services.agent.planning.query_plan_constraints import (
    collect_hard_constraints,
    constraint_value_from_mapping,
    constraint_values_equal,
    is_empty_constraint_value,
    protected_constraint_field_names,
)
from app.services.agent.planning.tool_plan_policy import (
    ONLINE_TOOL_NAMES,
)
from app.services.agent.planning.tool_plan_policy import (
    allowed_online_tools as _allowed_online_tools,
)
from app.services.agent.planning.tool_plan_policy import (
    online_recall_mode as _online_recall_mode,
)
from app.services.agent.planning.tool_plan_policy import (
    planned_tools as _planned_tools,
)
from app.services.agent.retrieval_evidence import (
    active_query_plan_fields,
    append_retrieval_evidence,
)
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.semantic_search import distinctive_query_terms, strip_scope
from app.services.agent.tools.local_db_search_tool import (
    LocalDbSearchTool,
    local_db_input_from_plan,
)
from app.services.agent.tools.web_search_tool import WebSearchTool

logger = logging.getLogger(__name__)

ReactActionName = Literal["stop", "refine_local_query", "expand_online_search"]

# 工具集合用于把 LangGraph 阶段生成的 tool_plan 映射到 ReAct 可执行动作。
_LOCAL_TOOLS = {"structured_sql", "sqlite_fts", "local_db_search"}
# 只允许 ReAct 追加或收紧这些软检索字段；硬约束字段必须保持原值。
_SOFT_PATCH_FIELDS = {
    "keywords",
    "category_hints",
    "requirement_terms",
    "compatibility_terms",
    "candidate_pool_limit",
    "keyword_match_mode",
}
# 复杂意图通常需要更高的证据覆盖度，单条命中不足以证明推荐或兼容结论。
_COMPLEX_TASK_TYPES = {
    "advisory",
    "compare",
    "comparison",
    "comparative",
    "compatibility",
    "ecosystem",
    "open_discovery",
    "risk",
}
_COMPLEX_QUERY_MARKERS = (
    "兼容",
    "冲突",
    "风险",
    "依赖",
    "前置",
    "替代",
    "对比",
    "比较",
    "推荐",
    "体系",
    "玩法",
    "framework",
    "compat",
    "requirement",
    "dependency",
    "alternative",
    "compare",
    "risk",
)
_DIRECT_IDENTITY_FIELDS = ("exact_title", "external_id", "source_url")


@dataclass(frozen=True)
class RetrievalQualityAssessment:
    """检索质量评估结果，决定是否进入 ReAct 补强。

    `weak_signals` 只记录弱信号，例如结果少；弱信号不会单独触发 ReAct。
    `reasons` 记录可执行的质量问题，例如直接身份缺失、硬约束冲突或证据不足。
    """

    trigger_react: bool
    quality_status: str
    reasons: list[str]
    weak_signals: list[str] = field(default_factory=list)
    hard_constraints_satisfied: bool = True
    evidence_coverage: str = "sufficient"
    direct_match_confidence: str = "unknown"
    intent_complexity: str = "simple"


@dataclass(frozen=True)
class ReactRetrievalAction:
    """一次受控 ReAct 动作。

    `query_plan_patch` 只能携带软字段或与硬约束完全相同的字段值；
    `expected_evidence` 用于说明本次动作希望补足哪类证据。
    """

    action: ReactActionName
    reason: str
    query: str = ""
    query_plan_patch: dict[str, Any] = field(default_factory=dict)
    expected_evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReactGuardDecision:
    """硬约束守卫的判定结果。"""

    allowed: bool
    reason: str = ""
    blocked_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BoundedReactRetrievalInput:
    """ReAct 子流程输入。

    `staged_results` 是前置检索阶段已经拿到的候选；
    `online_results` 是已有在线检索候选；`retrieval_evidence` 会被追加新的
    ReAct 证据片段。`max_rounds` 会被工具内部限制在 1 到 3 轮之间。
    """

    query: str
    query_plan: dict[str, Any]
    tool_plan: dict[str, Any]
    staged_results: list[SearchResult] = field(default_factory=list)
    online_results: list[SearchResult] = field(default_factory=list)
    retrieval_evidence: list[dict[str, object]] = field(default_factory=list)
    evidence_id: str = ""
    max_rounds: int = 2


@dataclass(frozen=True)
class BoundedReactRetrievalOutput:
    """ReAct 子流程输出。

    输出保留原有候选列表的结构，同时返回 `react_summary` 和 `react_trace`，
    供后续排序、接口响应和调试页面解释本轮是否触发、执行了什么、为何停止。
    """

    staged_results: list[SearchResult]
    online_results: list[SearchResult]
    retrieval_evidence: list[dict[str, object]]
    react_summary: dict[str, object]
    react_trace: list[dict[str, object]]


class BoundedReactRetrievalTool:
    """受控 ReAct 子流程：只在检索质量不足时执行有限、安全的补充检索动作。"""

    name = "bounded_react_retrieval"

    def __init__(self, session: Session):
        self.session = session

    async def run(self, tool_input: BoundedReactRetrievalInput) -> BoundedReactRetrievalOutput:
        """执行有限轮 ReAct 检索补强。

        每一轮都先评估当前候选质量，再选择一个安全动作。动作执行后只按
        规范化身份键合并新增结果，确保重复结果不会改变后续排序输入。
        """

        query_plan = dict(tool_input.query_plan or {})
        evidence_id = tool_input.evidence_id or str(query_plan.get("evidence_id") or "").strip()
        staged_results = list(tool_input.staged_results or [])
        online_results = list(tool_input.online_results or [])
        evidence = list(tool_input.retrieval_evidence or [])
        react_trace: list[dict[str, object]] = []
        executed_actions: list[str] = []
        seen_actions: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
        stop_reason = "not_started"
        max_rounds = max(1, min(3, int(tool_input.max_rounds or 1)))

        for round_index in range(1, max_rounds + 1):
            # Thought：只基于当前证据质量判断是否需要补检索，不用结果数量做硬触发。
            assessment = assess_retrieval_quality(
                query=tool_input.query,
                query_plan=query_plan,
                staged_results=staged_results,
                online_results=online_results,
            )
            # Action：动作必须来自固定集合，且受 tool_plan 与硬约束守卫限制。
            action = _decide_action(
                query=tool_input.query,
                query_plan=query_plan,
                tool_plan=tool_input.tool_plan or {},
                retrieval_evidence=evidence,
                assessment=assessment,
            )
            trace_item: dict[str, object] = {
                "round": round_index,
                "quality_status": assessment.quality_status,
                "trigger_react": assessment.trigger_react,
                "reasons": assessment.reasons,
                "weak_signals": assessment.weak_signals,
                "evidence_coverage": assessment.evidence_coverage,
                "hard_constraints_satisfied": assessment.hard_constraints_satisfied,
                "direct_match_confidence": assessment.direct_match_confidence,
                "intent_complexity": assessment.intent_complexity,
                "action": action.action,
                "action_reason": action.reason,
            }

            if action.action == "stop":
                # 质量充足或没有安全动作时，记录跳过证据，方便前端解释未触发原因。
                stop_reason = action.reason
                trace_item["status"] = "skipped"
                react_trace.append(trace_item)
                _append_react_evidence(
                    evidence,
                    status="skipped",
                    reason=action.reason,
                    count=len(staged_results) + len(online_results),
                    query_plan=query_plan,
                    evidence_id=evidence_id,
                )
                break

            signature = _action_signature(action)
            if signature in seen_actions:
                # 避免在同一查询和同一补丁上重复执行相同工具，防止无收益循环。
                stop_reason = "repeated_action_blocked"
                trace_item["status"] = "blocked"
                trace_item["guard_reason"] = stop_reason
                react_trace.append(trace_item)
                _append_react_evidence(
                    evidence,
                    status="blocked",
                    reason=stop_reason,
                    count=len(staged_results) + len(online_results),
                    query_plan=query_plan,
                    evidence_id=evidence_id,
                )
                break
            seen_actions.add(signature)

            guard = guard_react_action(query_plan, action)
            if not guard.allowed:
                # 硬约束守卫负责兜底：ReAct 不能改写用户明确限定的来源、游戏或身份。
                stop_reason = guard.reason or "hard_constraint_guard_blocked"
                trace_item["status"] = "blocked"
                trace_item["guard_reason"] = stop_reason
                trace_item["blocked_fields"] = guard.blocked_fields
                react_trace.append(trace_item)
                _append_react_evidence(
                    evidence,
                    status="blocked",
                    reason=stop_reason,
                    count=len(staged_results) + len(online_results),
                    query_plan=query_plan,
                    evidence_id=evidence_id,
                )
                break

            before_keys = _result_keys([*staged_results, *online_results])
            if action.action == "refine_local_query":
                # 本地细化只扩展软字段，适合在线工具不可用或计划中没有在线工具的场景。
                refined_plan = _query_plan_with_patch(query_plan, action.query_plan_patch)
                local_results = await LocalDbSearchTool(self.session).run(
                    local_db_input_from_plan(action.query or tool_input.query, {**refined_plan, "evidence_id": evidence_id})
                )
                staged_results = _merge_results(staged_results, local_results)
                executed_actions.append(action.action)
                trace_item["status"] = "succeeded"
                trace_item["result_count"] = len(local_results)
                _append_react_evidence(
                    evidence,
                    status="succeeded",
                    reason=action.reason,
                    count=len(local_results),
                    query_plan=refined_plan,
                    evidence_id=evidence_id,
                )
            elif action.action == "expand_online_search":
                # 在线扩展沿用 tool_plan 的在线召回策略，避免越权调用未规划的来源。
                expanded_plan = _query_plan_with_patch(query_plan, action.query_plan_patch)
                web_output = await WebSearchTool(self.session).run(
                    query=action.query or tool_input.query,
                    query_plan={**expanded_plan, "evidence_id": evidence_id},
                    evidence_id=evidence_id,
                    online_recall_mode=_online_recall_mode(tool_input.tool_plan or {}),
                    allowed_tools=_allowed_online_tools(_planned_tools(tool_input.tool_plan or {})),
                )
                online_results = _merge_results(online_results, web_output.results)
                evidence.extend(_namespaced_react_web_evidence(web_output.evidence, existing_evidence=evidence))
                executed_actions.append(action.action)
                trace_item["status"] = "succeeded"
                trace_item["result_count"] = len(web_output.results)
                _append_react_evidence(
                    evidence,
                    status="succeeded",
                    reason=action.reason,
                    count=len(web_output.results),
                    query_plan=expanded_plan,
                    evidence_id=evidence_id,
                )

            # Observation：只把去重后真正新增的候选视为有效收益。
            after_keys = _result_keys([*staged_results, *online_results])
            new_result_count = len(after_keys - before_keys)
            trace_item["new_result_count"] = new_result_count
            react_trace.append(trace_item)
            logger.info(
                "agent.tool name=bounded_react_retrieval action=%s status=%s results=%s new_results=%s evidence_id=%s",
                action.action,
                trace_item.get("status"),
                trace_item.get("result_count", 0),
                new_result_count,
                evidence_id,
            )

            if new_result_count <= 0:
                stop_reason = "no_new_useful_results"
                break
            stop_reason = "round_limit_reached"

        if not react_trace:
            # 理论兜底：即使未来 max_rounds 或入口条件改变，也保证输出可解释 trace。
            assessment = assess_retrieval_quality(
                query=tool_input.query,
                query_plan=query_plan,
                staged_results=staged_results,
                online_results=online_results,
            )
            stop_reason = "quality_sufficient" if not assessment.trigger_react else "no_safe_action"
            react_trace.append(
                {
                    "round": 1,
                    "quality_status": assessment.quality_status,
                    "trigger_react": assessment.trigger_react,
                    "reasons": assessment.reasons,
                    "weak_signals": assessment.weak_signals,
                    "action": "stop",
                    "action_reason": stop_reason,
                    "status": "skipped",
                }
            )

        first_trace = react_trace[0] if react_trace else {}
        final_trace = react_trace[-1] if react_trace else {}
        # 汇总字段面向接口和文档，不暴露内部对象，便于前端稳定展示。
        react_summary: dict[str, object] = {
            "strategy": self.name,
            "triggered": bool(executed_actions),
            "quality_triggered": bool(first_trace.get("trigger_react")),
            "round_count": len(react_trace),
            "executed_actions": executed_actions,
            "stop_reason": stop_reason,
            "quality_status": final_trace.get("quality_status", "unknown"),
            "staged_count": len(staged_results),
            "online_count": len(online_results),
        }
        return BoundedReactRetrievalOutput(
            staged_results=staged_results,
            online_results=online_results,
            retrieval_evidence=evidence,
            react_summary=react_summary,
            react_trace=react_trace,
        )


def assess_retrieval_quality(
    *,
    query: str,
    query_plan: dict[str, Any],
    staged_results: list[SearchResult],
    online_results: list[SearchResult],
) -> RetrievalQualityAssessment:
    """评估当前候选是否需要 ReAct 补强。

    策略刻意保守：少于 3 条结果只作为弱信号；真正触发补强的是无结果、
    硬约束冲突、直接身份缺失、复杂意图证据不足等可解释问题。
    """

    results = [*(staged_results or []), *(online_results or [])]
    hard_constraints = collect_hard_constraints(query_plan, _semantic_hard_filters(query_plan))
    hard_violations = _hard_constraint_violations(results, hard_constraints)
    identity_required = _has_direct_identity(query_plan)
    direct_match_confidence = _direct_match_confidence(results, query_plan)
    intent_complexity = "complex" if _is_complex_intent(query, query_plan) else "simple"
    evidence_coverage = _evidence_coverage(results, query_plan, intent_complexity=intent_complexity)

    reasons: list[str] = []
    weak_signals: list[str] = []
    if len(results) < 3:
        weak_signals.append("low_result_count")
    if not results:
        reasons.append("no_results")
    if hard_violations:
        reasons.append("hard_constraint_violation")
    if identity_required and direct_match_confidence == "missing":
        reasons.append("direct_match_missing_for_specific_query")
    if intent_complexity == "complex" and evidence_coverage in {"missing", "insufficient"}:
        reasons.append("evidence_insufficient_for_intent")
    if is_open_discovery_plan(query_plan) and not results:
        reasons.append("low_confidence_open_discovery")

    strong_reasons = [reason for reason in reasons if reason != "no_results"]
    trigger_react = bool(strong_reasons) or (not results and (intent_complexity == "complex" or is_open_discovery_plan(query_plan)))
    if not trigger_react and not results and _has_distinctive_or_planned_terms(query, query_plan):
        trigger_react = True
    if trigger_react:
        quality_status = "insufficient" if "no_results" in reasons or evidence_coverage == "missing" else "partial"
    else:
        quality_status = "sufficient"

    return RetrievalQualityAssessment(
        trigger_react=trigger_react,
        quality_status=quality_status,
        reasons=unique_text(reasons, limit=8),
        weak_signals=unique_text(weak_signals, limit=8),
        hard_constraints_satisfied=not hard_violations,
        evidence_coverage=evidence_coverage,
        direct_match_confidence=direct_match_confidence,
        intent_complexity=intent_complexity,
    )


def guard_react_action(query_plan: dict[str, Any], action: ReactRetrievalAction) -> ReactGuardDecision:
    """校验 ReAct 动作是否会破坏硬约束。

    允许动作重复携带与硬约束完全相同的字段值，禁止删除、放宽或替换硬约束。
    """

    hard_constraints = collect_hard_constraints(query_plan, _semantic_hard_filters(query_plan))
    protected_fields = protected_constraint_field_names(hard_constraints)
    patch = dict(action.query_plan_patch or {})
    unexpected_fields = sorted(set(patch) - _SOFT_PATCH_FIELDS - protected_fields)
    if unexpected_fields:
        return ReactGuardDecision(False, "unsupported_query_plan_patch", unexpected_fields)

    blocked_fields: list[str] = []
    for field_name in protected_fields:
        if field_name not in patch:
            continue
        canonical_value = constraint_value_from_mapping(field_name, hard_constraints)
        patch_value = patch.get(field_name)
        if is_empty_constraint_value(patch_value) or not constraint_values_equal(canonical_value, patch_value):
            blocked_fields.append(field_name)
    if blocked_fields:
        return ReactGuardDecision(False, "hard_constraint_change_blocked", sorted(blocked_fields))
    return ReactGuardDecision(True)


def _decide_action(
    *,
    query: str,
    query_plan: dict[str, Any],
    tool_plan: dict[str, Any],
    retrieval_evidence: list[dict[str, object]],
    assessment: RetrievalQualityAssessment,
) -> ReactRetrievalAction:
    """根据质量评估和工具计划选择下一步动作。

    优先在线扩展可验证来源；在线工具已终止跳过或不可用时，才退回本地细化。
    如果没有安全动作，明确返回 stop，避免隐式改变检索策略。
    """

    if not assessment.trigger_react:
        return ReactRetrievalAction("stop", "quality_sufficient")

    planned_tools = _planned_tools(tool_plan)
    refined_query = _refined_query(query, query_plan)
    patch = _soft_query_plan_patch(query_plan)
    online_allowed = bool(planned_tools & ONLINE_TOOL_NAMES)
    local_allowed = bool(planned_tools & _LOCAL_TOOLS) or not planned_tools
    online_reasons = {
        "direct_match_missing_for_specific_query",
        "evidence_insufficient_for_intent",
        "hard_constraint_violation",
        "low_confidence_open_discovery",
        "no_results",
    }
    online_unavailable = _online_unavailable_from_prior_evidence(
        retrieval_evidence,
        allowed_tools=_allowed_online_tools(planned_tools),
    )
    if online_allowed and not online_unavailable and set(assessment.reasons) & online_reasons:
        return ReactRetrievalAction(
            "expand_online_search",
            "quality_control_expand_online",
            query=refined_query,
            query_plan_patch=patch,
            expected_evidence=["online_source_result", "source_identity", "summary_or_metadata"],
        )
    if local_allowed and patch:
        reason = "online_unavailable_refine_local_query" if online_unavailable else "quality_control_refine_local_query"
        return ReactRetrievalAction(
            "refine_local_query",
            reason,
            query=refined_query,
            query_plan_patch=patch,
            expected_evidence=["local_candidate", "metadata_match"],
        )
    stop_reason = "online_unavailable_no_safe_action" if online_unavailable else "no_safe_action"
    return ReactRetrievalAction("stop", stop_reason)


def _semantic_hard_filters(query_plan: dict[str, Any]) -> dict[str, Any]:
    """提取语义规划阶段写入的硬过滤条件。"""

    semantic = query_plan.get("_agent_semantic_strategy")
    if isinstance(semantic, dict) and isinstance(semantic.get("hard_filters"), dict):
        return dict(semantic["hard_filters"])
    return {}


def _hard_constraint_violations(results: list[SearchResult], hard_constraints: dict[str, Any]) -> list[str]:
    """检查候选是否违反来源、游戏、成人内容或直接身份约束。"""

    if not results:
        return []
    violations: list[str] = []
    sources = _lower_set(hard_constraints.get("sources"))
    excluded_sources = _lower_set(hard_constraints.get("excluded_sources"))
    games = _lower_set(hard_constraints.get("games"))
    game_domains = _lower_set(hard_constraints.get("game_domains"))
    adult_content = hard_constraints.get("adult_content")

    for result in results:
        mod = result.mod
        source = _norm(getattr(mod, "source", ""))
        if sources and source not in sources:
            violations.append("sources")
        if excluded_sources and source in excluded_sources:
            violations.append("excluded_sources")
        if games and _norm(getattr(mod, "game", "")) not in games:
            violations.append("games")
        if game_domains and _norm(getattr(mod, "game_domain", "")) not in game_domains:
            violations.append("game_domains")
        if isinstance(adult_content, bool) and mod.adult_content is not None and bool(mod.adult_content) is not adult_content:
            violations.append("adult_content")

    if hard_constraints.get("exact_title") and not _has_exact_title_match(results, str(hard_constraints["exact_title"])):
        violations.append("exact_title")
    if hard_constraints.get("external_id") and not _has_external_id_match(results, str(hard_constraints["external_id"])):
        violations.append("external_id")
    if hard_constraints.get("source_url") and not _has_source_url_match(results, str(hard_constraints["source_url"])):
        violations.append("source_url")
    return unique_text(violations, limit=16)


def _has_direct_identity(query_plan: dict[str, Any]) -> bool:
    return any(str(query_plan.get(field) or "").strip() for field in _DIRECT_IDENTITY_FIELDS)


def _direct_match_confidence(results: list[SearchResult], query_plan: dict[str, Any]) -> str:
    """判断精确标题、外部 ID 或来源 URL 是否已有直接命中。"""

    if not _has_direct_identity(query_plan):
        return "unknown"
    if query_plan.get("exact_title") and _has_exact_title_match(results, str(query_plan["exact_title"])):
        return "high"
    if query_plan.get("external_id") and _has_external_id_match(results, str(query_plan["external_id"])):
        return "high"
    if query_plan.get("source_url") and _has_source_url_match(results, str(query_plan["source_url"])):
        return "high"
    return "missing"


def _has_exact_title_match(results: list[SearchResult], title: str) -> bool:
    expected = _norm(title)
    if not expected:
        return False
    for result in results:
        titles = [
            getattr(result.mod, "title", ""),
            getattr(result.mod, "translated_title_zh", ""),
        ]
        if any(_norm(item) == expected for item in titles):
            return True
    return False


def _has_external_id_match(results: list[SearchResult], external_id: str) -> bool:
    expected = _norm_identity(external_id)
    if not expected:
        return False
    for result in results:
        actual = _norm_identity(getattr(result.mod, "external_id", ""))
        if actual == expected or actual.endswith(f":{expected}") or expected.endswith(f":{actual}"):
            return True
    return False


def _has_source_url_match(results: list[SearchResult], source_url: str) -> bool:
    expected = _norm_url(source_url)
    if not expected:
        return False
    for result in results:
        actual = _norm_url(getattr(result.mod, "url", ""))
        if actual and actual == expected:
            return True
    return False


def _is_complex_intent(query: str, query_plan: dict[str, Any]) -> bool:
    """识别需要多证据支撑的复杂意图。"""

    text = str(query or "").lower()
    semantic = query_plan.get("_agent_semantic_strategy")
    task_type = ""
    if isinstance(semantic, dict):
        task_type = str(semantic.get("task_type") or semantic.get("intent") or "").strip().lower()
    semantic_domains = _lower_set(query_plan.get("_agent_semantic_domains"))
    semantic_anchors = _lower_set(query_plan.get("_agent_semantic_anchors"))
    return (
        is_open_discovery_plan(query_plan)
        or task_type in _COMPLEX_TASK_TYPES
        or bool(semantic_domains & {"mechanics", "source_scope", "risk", "compatibility"})
        or bool(semantic_anchors & {"framework", "roleplay", "pregnancy"})
        or bool(string_list(query_plan.get("requirement_terms")))
        or bool(string_list(query_plan.get("compatibility_terms")))
        or any(marker in text for marker in _COMPLEX_QUERY_MARKERS)
    )


def _evidence_coverage(
    results: list[SearchResult],
    query_plan: dict[str, Any],
    *,
    intent_complexity: str,
) -> str:
    """估计候选文本是否足以支撑复杂查询的结论。"""

    if not results:
        return "missing"
    if intent_complexity != "complex":
        return "sufficient"
    expected_terms = _expected_evidence_terms(query_plan)
    evidence_texts = [_result_text(result) for result in results[:5]]
    textful_count = sum(1 for text in evidence_texts if text)
    if textful_count == 0:
        return "insufficient"
    if expected_terms and not any(term in text for term in expected_terms for text in evidence_texts):
        return "insufficient"
    if textful_count < min(2, len(results[:5])):
        return "partial"
    return "sufficient"


def _expected_evidence_terms(query_plan: dict[str, Any]) -> list[str]:
    terms = [
        *string_list(query_plan.get("requirement_terms"), limit=8),
        *string_list(query_plan.get("compatibility_terms"), limit=8),
        *string_list(query_plan.get("category_hints"), limit=8),
    ]
    return [_norm(term) for term in unique_text(terms, limit=12) if _norm(term)]


def _has_distinctive_or_planned_terms(query: str, query_plan: dict[str, Any]) -> bool:
    return bool(
        distinctive_query_terms(query)
        or string_list(query_plan.get("keywords"))
        or string_list(query_plan.get("requirement_terms"))
        or string_list(query_plan.get("compatibility_terms"))
    )


def _refined_query(query: str, query_plan: dict[str, Any]) -> str:
    """把原始问题和已抽取软字段合并成补检索查询。"""

    visible_query = strip_scope(query)
    additions = [
        *string_list(query_plan.get("keywords"), limit=6),
        *string_list(query_plan.get("requirement_terms"), limit=4),
        *string_list(query_plan.get("compatibility_terms"), limit=4),
        *string_list(query_plan.get("category_hints"), limit=4),
    ]
    return " ".join(unique_text([visible_query, *additions], limit=16)) or visible_query


def _soft_query_plan_patch(query_plan: dict[str, Any]) -> dict[str, Any]:
    """生成只包含软字段的查询计划补丁。"""

    patch: dict[str, Any] = {}
    terms = [
        *string_list(query_plan.get("keywords"), limit=8),
        *string_list(query_plan.get("requirement_terms"), limit=4),
        *string_list(query_plan.get("compatibility_terms"), limit=4),
        *string_list(query_plan.get("category_hints"), limit=4),
    ]
    keywords = unique_text([*string_list(query_plan.get("keywords")), *terms], limit=12)
    if keywords != string_list(query_plan.get("keywords")):
        patch["keywords"] = keywords
    if string_list(query_plan.get("requirement_terms")):
        patch["requirement_terms"] = string_list(query_plan.get("requirement_terms"), limit=8)
    if string_list(query_plan.get("compatibility_terms")):
        patch["compatibility_terms"] = string_list(query_plan.get("compatibility_terms"), limit=8)
    if string_list(query_plan.get("category_hints")):
        patch["category_hints"] = string_list(query_plan.get("category_hints"), limit=8)
    if not query_plan.get("candidate_pool_limit"):
        patch["candidate_pool_limit"] = 30
    return patch


def _query_plan_with_patch(query_plan: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """应用查询计划补丁，并用 SearchPlan 做结构校验。"""

    plan = dict(query_plan or {})
    for key, value in (patch or {}).items():
        if value not in (None, "", []):
            plan[key] = value
    SearchPlan.from_query_plan(plan)
    return plan


def _merge_results(existing: list[SearchResult], additions: list[SearchResult]) -> list[SearchResult]:
    """按来源和稳定身份键合并结果，保持原结果优先。"""

    merged: list[SearchResult] = []
    seen: set[tuple[str, str]] = set()
    for result in [*(existing or []), *(additions or [])]:
        key = _result_key(result)
        if key in seen:
            continue
        merged.append(result)
        seen.add(key)
    return merged


def _result_keys(results: list[SearchResult]) -> set[tuple[str, str]]:
    return {_result_key(result) for result in results}


def _result_key(result: SearchResult) -> tuple[str, str]:
    mod = result.mod
    source = _norm(getattr(mod, "source", ""))
    external_id = _norm_identity(getattr(mod, "external_id", ""))
    if external_id:
        return source, f"id:{external_id}"
    url = _norm_url(getattr(mod, "url", ""))
    if url:
        return source, f"url:{url}"
    return source, f"title:{_norm(getattr(mod, 'title', ''))}"


def _result_text(result: SearchResult) -> str:
    mod = result.mod
    values = [
        getattr(mod, "title", ""),
        getattr(mod, "translated_title_zh", ""),
        getattr(mod, "category", ""),
        getattr(mod, "original_summary", ""),
        getattr(mod, "translated_summary", ""),
        getattr(mod, "version", ""),
        result.rank_reason or "",
    ]
    return _norm(" ".join(str(value or "") for value in values))


def _append_react_evidence(
    evidence: list[dict[str, object]],
    *,
    status: str,
    reason: str,
    count: int,
    query_plan: dict[str, Any],
    evidence_id: str,
) -> None:
    append_retrieval_evidence(
        evidence,
        stage="bounded_react_retrieval",
        tool="bounded_react_controller",
        status=status,
        count=count,
        reason=reason,
        fields=active_query_plan_fields(query_plan),
        query_plan=query_plan,
        evidence_id=evidence_id,
        fragment_prefix="r_react",
    )


def _namespaced_react_web_evidence(
    web_evidence: list[dict[str, object]],
    *,
    existing_evidence: list[dict[str, object]],
) -> list[dict[str, object]]:
    """为 ReAct 触发的在线证据重新分配片段 ID，避免与前置在线检索冲突。"""

    used_ids = {
        str(item.get("fragment_id") or "").strip()
        for item in [*(existing_evidence or []), *(web_evidence or [])]
        if str(item.get("fragment_id") or "").strip()
    }
    next_index = 1
    namespaced: list[dict[str, object]] = []
    for item in web_evidence or []:
        copied = dict(item)
        while f"r_react_web_{next_index}" in used_ids:
            next_index += 1
        fragment_id = f"r_react_web_{next_index}"
        copied["fragment_id"] = fragment_id
        used_ids.add(fragment_id)
        namespaced.append(copied)
        next_index += 1
    return namespaced


def _online_unavailable_from_prior_evidence(
    retrieval_evidence: list[dict[str, object]],
    *,
    allowed_tools: set[str],
) -> bool:
    """根据既有证据判断在线工具是否已经终止性不可用。"""

    if not retrieval_evidence or not allowed_tools:
        return False
    relevant: list[dict[str, object]] = []
    for item in retrieval_evidence:
        if item.get("stage") != "online_retrieval":
            continue
        tool = str(item.get("tool") or "").strip()
        if tool in allowed_tools:
            relevant.append(item)
    if not relevant:
        return False
    if any(str(item.get("status") or "").strip() in {"succeeded", "degraded"} for item in relevant):
        return False
    terminal_skip_reasons = {"missing_credentials", "source_filter", "not_planned"}
    return all(
        str(item.get("status") or "").strip() == "skipped"
        and str(item.get("reason") or "").strip() in terminal_skip_reasons
        for item in relevant
    )


def _action_signature(action: ReactRetrievalAction) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    patch_items = tuple(sorted((str(key), str(value)) for key, value in action.query_plan_patch.items()))
    return action.action, action.query, patch_items


def _lower_set(value: object) -> set[str]:
    return {_norm(item) for item in string_list(value) if _norm(item)}


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _norm_identity(value: object) -> str:
    return str(value or "").strip().lower()


def _norm_url(value: object) -> str:
    text = url_without_query(str(value or "").strip()).lower()
    return text[:-1] if text.endswith("/") else text

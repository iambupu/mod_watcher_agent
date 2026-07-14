import re
from typing import Any

from app.services.agent.planning.query_plan_contract import semantic_strategy
from app.services.agent.schemas import AgentModMatch


def judge_summary(query_plan: dict[str, Any] | None) -> dict[str, Any]:
    value = (query_plan or {}).get("_agent_candidate_semantic_judge") if isinstance(query_plan, dict) else None
    return value if isinstance(value, dict) else {}


def answer_contract_payload(query_plan: dict[str, Any] | None) -> str:
    strategy = semantic_strategy(query_plan)
    judge = judge_summary(query_plan)
    if not strategy and not judge:
        return ""
    parts = []
    if strategy:
        parts.extend(
            [
                f"primary_goal={strategy.get('user_goal') or ''}",
                f"direct_match_definition={strategy.get('direct_match_definition') or []}",
                f"support_context_definition={strategy.get('support_context_definition') or []}",
                f"reject_as_primary={strategy.get('reject_as_primary') or []}",
                f"answer_policy={strategy.get('answer_policy') or {}}",
            ]
        )
    if judge:
        parts.extend(
            [
                f"fit_counts={judge.get('fit_counts') or {}}",
                f"candidate_judgements={_compact_judgements(judge)}",
                f"gaps={judge.get('gaps') or []}",
            ]
        )
    return "\n".join(parts)


def candidate_fit_metadata(query_plan: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    items = judge_summary(query_plan).get("judgements") or []
    metadata: dict[int, dict[str, Any]] = {}
    if not isinstance(items, list):
        return metadata
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("candidate_id"), int):
            continue
        metadata[int(item["candidate_id"])] = {
            "fit_type": str(item.get("fit_type") or "uncertain"),
            "evidence": item.get("evidence") if isinstance(item.get("evidence"), list) else [],
            "violations": item.get("violations") if isinstance(item.get("violations"), list) else [],
        }
    return metadata


def repair_contract_answer_claims(
    answer: str,
    query_plan: dict[str, Any] | None,
    *,
    matches: list[AgentModMatch] | None = None,
) -> str:
    text = str(answer or "").strip()
    has_support = _has_support_fit(query_plan, matches=matches)
    has_uncertain = _has_uncertain_fit(query_plan, matches=matches)
    if not text or not (has_support or has_uncertain):
        return text
    correction = _non_direct_correction(has_support=has_support, has_uncertain=has_uncertain)
    patterns = [
        r"以上结果严格遵循[^。\n]*(?:未包含|没有包含)[^。\n]*。",
        r"以上推荐严格遵循[^。\n]*(?:未包含|没有包含)[^。\n]*。",
        r"以上结果均[^。\n]*(?:符合|满足)[^。\n]*。",
        r"以上推荐均[^。\n]*(?:符合|满足)[^。\n]*。",
    ]
    repaired = text
    for pattern in patterns:
        repaired = re.sub(pattern, correction, repaired)
    misleading_fragments = [
        "未包含非直接匹配内容",
        "未包含非主目标内容",
        "未包含非服装类内容",
        "没有包含非直接匹配内容",
        "没有包含非主目标内容",
        "没有包含非服装类内容",
    ]
    if any(fragment in repaired for fragment in misleading_fragments):
        replacement = _misleading_fragment_replacement(has_support=has_support, has_uncertain=has_uncertain)
        for fragment in misleading_fragments:
            repaired = repaired.replace(fragment, replacement)
    if repaired != text:
        return repaired.strip()
    if has_uncertain and not _answer_marks_uncertainty(repaired):
        return f"{repaired}\n\n{_uncertain_notice(has_support=has_support)}"
    if has_support and ("辅助参考" in repaired or "非主推荐" in repaired):
        return f"{repaired}\n\n{correction}"
    return repaired


def partition_matches_by_fit(
    matches: list[AgentModMatch],
    query_plan: dict[str, Any] | None,
) -> tuple[list[AgentModMatch], list[AgentModMatch], list[AgentModMatch]]:
    fit_by_id = {
        int(item["candidate_id"]): str(item.get("fit_type") or "")
        for item in (judge_summary(query_plan).get("judgements") or [])
        if isinstance(item, dict) and isinstance(item.get("candidate_id"), int)
    }
    direct: list[AgentModMatch] = []
    support: list[AgentModMatch] = []
    uncertain: list[AgentModMatch] = []
    for match in matches:
        fit_type = fit_by_id.get(match.id, "direct_match")
        if fit_type == "support_context":
            support.append(match)
        elif fit_type == "uncertain":
            uncertain.append(match)
        elif fit_type == "off_scope":
            continue
        else:
            direct.append(match)
    return direct, support, uncertain


def _compact_judgements(judge: dict[str, Any]) -> list[dict[str, object]]:
    items = judge.get("judgements")
    if not isinstance(items, list):
        return []
    compacted = []
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                "candidate_id": item.get("candidate_id"),
                "fit_type": item.get("fit_type"),
                "relevance": item.get("relevance"),
                "group": item.get("group"),
                "category_semantic_compatibility": item.get("category_semantic_compatibility"),
                "category_compatibility_reason": item.get("category_compatibility_reason") or "",
                "violations": item.get("violations") or [],
                "reason": item.get("reason") or "",
            }
        )
    return compacted


def _non_direct_correction(*, has_support: bool, has_uncertain: bool) -> str:
    if has_support and has_uncertain:
        return "主推荐符合本轮目标；辅助参考仅用于搭配说明，证据不足/待确认的候选需要进一步核查，二者都不作为主结果。"
    if has_uncertain:
        return "主推荐符合本轮目标；证据不足/待确认的候选需要进一步核查，不作为主结果。"
    return "主推荐符合本轮目标；辅助参考仅用于搭配说明，不作为主结果。"


def _misleading_fragment_replacement(*, has_support: bool, has_uncertain: bool) -> str:
    if has_support and has_uncertain:
        return "辅助项和待确认项不作为直接匹配内容"
    if has_uncertain:
        return "待确认项不作为直接匹配内容"
    return "辅助项不作为直接匹配内容"


def _uncertain_notice(*, has_support: bool) -> str:
    if has_support:
        return "存在证据不足/待确认的候选；辅助参考和待确认项都不作为主推荐，需要进一步核查缺失证据。"
    return "存在证据不足/待确认的候选；这些候选不作为主推荐，需要进一步核查缺失证据。"


def _has_support_fit(query_plan: dict[str, Any] | None, *, matches: list[AgentModMatch] | None = None) -> bool:
    return "support_context" in _fit_types_in_scope(query_plan, matches=matches)


def _has_uncertain_fit(query_plan: dict[str, Any] | None, *, matches: list[AgentModMatch] | None = None) -> bool:
    return "uncertain" in _fit_types_in_scope(query_plan, matches=matches)


def _fit_types_in_scope(query_plan: dict[str, Any] | None, *, matches: list[AgentModMatch] | None = None) -> set[str]:
    judge = judge_summary(query_plan)
    scoped_ids = {match.id for match in matches} if matches is not None else None
    fit_types: set[str] = set()
    fit_counts = judge.get("fit_counts")
    if scoped_ids is None and isinstance(fit_counts, dict):
        for key in ["support_context", "uncertain", "direct_match", "off_scope"]:
            value = fit_counts.get(key)
            if isinstance(value, int) and value > 0:
                fit_types.add(key)
    for item in judge.get("judgements") or []:
        if not isinstance(item, dict):
            continue
        candidate_id = item.get("candidate_id")
        if scoped_ids is not None and candidate_id not in scoped_ids:
            continue
        fit_type = str(item.get("fit_type") or "").strip()
        if fit_type:
            fit_types.add(fit_type)
    return fit_types


def _answer_marks_uncertainty(answer: str) -> bool:
    return any(marker in str(answer or "") for marker in ["证据不足", "待确认", "不确定", "未明确"])

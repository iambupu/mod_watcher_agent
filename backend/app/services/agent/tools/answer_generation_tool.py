import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.answer_service import (
    AgentAnswerService,
    build_alternative_fallback,
    build_comparison_fallback,
    build_contract_fallback_answer,
    build_fallback_answer,
    build_install_risk_fallback,
    build_recommendation_fallback,
)
from app.services.agent.schemas import AgentHistoryItem, AgentModMatch
from app.services.agent.tools.llm_output import is_empty_or_error_content

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnswerGenerationInput:
    query: str
    query_plan: dict[str, Any] = field(default_factory=dict)
    matches: list[AgentModMatch] = field(default_factory=list)
    llm_available: bool = False
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    history: list[AgentHistoryItem] = field(default_factory=list)
    evidence_id: str = ""


@dataclass(frozen=True)
class AnswerGenerationOutput:
    answer: str
    used_llm: bool
    next_steps: list[str] = field(default_factory=list)
    reason: str = ""


class AnswerGenerationTool:
    """生成用户可见回答；LLM 不可用时回退到确定性回答。"""

    name = "answer_generation"

    async def run(self, tool_input: AnswerGenerationInput) -> AnswerGenerationOutput:
        if not tool_input.matches:
            return self._fallback(
                tool_input,
                reason="no_matches",
                answer=_no_match_answer(tool_input.query, tool_input.query_plan),
            )
        self_correction_answer = _self_correction_no_direct_answer(tool_input.query_plan, tool_input.matches)
        if self_correction_answer:
            return self._fallback(
                tool_input,
                reason="self_correction_no_direct",
                answer=self_correction_answer,
            )

        fallback_answer = _fallback_answer_for_intent(tool_input.query_plan.get("intent"), tool_input.matches, tool_input.query_plan)
        if not tool_input.llm_available:
            return self._fallback(tool_input, reason="llm_unavailable", answer=fallback_answer)

        answer_service = AgentAnswerService()
        content = await answer_service.answer_matches(
            query=tool_input.query,
            query_plan=tool_input.query_plan,
            matches=tool_input.matches,
            provider=tool_input.provider,
            api_key=tool_input.api_key,
            base_url=tool_input.base_url,
            model=tool_input.model,
            history=tool_input.history,
        )
        if is_empty_or_error_content(content):
            return self._fallback(tool_input, reason="llm_empty_or_error", answer=fallback_answer)

        answer = content.strip()
        try:
            next_steps = await answer_service.suggest_next_steps(
                query=tool_input.query,
                answer=answer,
                matches=tool_input.matches,
                provider=tool_input.provider,
                api_key=tool_input.api_key,
                base_url=tool_input.base_url,
                model=tool_input.model,
            )
        except Exception as exc:  # pragma: no cover - defensive degradation path
            logger.info(
                "agent.tool name=answer_generation status=degraded reason=next_steps_%s matches=%s evidence_id=%s",
                type(exc).__name__,
                len(tool_input.matches),
                tool_input.evidence_id,
            )
            next_steps = []
        logger.info(
            "agent.tool name=answer_generation status=succeeded mode=llm matches=%s next_steps=%s evidence_id=%s",
            len(tool_input.matches),
            len(next_steps),
            tool_input.evidence_id,
        )
        logger.info("agent.answer status=llm matches=%s next_steps=%s", len(tool_input.matches), len(next_steps))
        return AnswerGenerationOutput(answer=answer, used_llm=True, next_steps=next_steps, reason="llm")

    def _fallback(self, tool_input: AnswerGenerationInput, *, reason: str, answer: str) -> AnswerGenerationOutput:
        logger.info(
            "agent.tool name=answer_generation status=succeeded mode=fallback reason=%s matches=%s evidence_id=%s",
            reason,
            len(tool_input.matches),
            tool_input.evidence_id,
        )
        logger.info("agent.answer status=fallback reason=%s matches=%s", reason, len(tool_input.matches))
        return AnswerGenerationOutput(answer=answer, used_llm=False, reason=reason)


def _no_match_answer(query: str = "", query_plan: dict[str, Any] | None = None) -> str:
    filters = _no_match_filter_summary(query_plan)
    if filters:
        return (
            "没有找到明确匹配。\n"
            "当前筛选条件下没有足够明确的结果。\n"
            f"已应用约束：{filters}。\n"
            "可以尝试放宽其中一个条件，例如取消来源限制、放宽分类，或先查看同游戏的相关配套候选。"
        )
    current_query = str(query or "").strip()
    if current_query:
        return (
            "没有找到明确匹配。\n"
            f"本轮问题：{current_query}\n"
            "当前候选中没有足够明确的直接命中项。\n"
            "可以补充游戏名、来源、分类，或放宽本轮目标词后再查。"
        )
    return (
        "没有找到明确匹配。\n"
        "当前候选中没有足够明确的直接命中项。\n"
        "可以补充游戏名、来源、分类，或放宽本轮目标词后再查。"
    )


def _no_match_filter_summary(query_plan: dict[str, Any] | None) -> str:
    if not isinstance(query_plan, dict):
        return ""
    parts: list[str] = []
    games = _string_values(query_plan.get("games")) or _string_values(query_plan.get("game_domains"))
    sources = _string_values(query_plan.get("sources"))
    categories = _string_values(query_plan.get("categories"))
    if games:
        parts.append(f"游戏：{', '.join(games)}")
    if categories:
        parts.append(f"类型：{', '.join(categories)}")
    if sources:
        parts.append(f"来源：{', '.join(sources)}")
    adult_content = query_plan.get("adult_content")
    if isinstance(adult_content, bool):
        parts.append(f"内容分级：{'NSFW' if adult_content else 'SFW'}")
    return "；".join(parts)


def _self_correction_no_direct_answer(
    query_plan: dict[str, Any] | None,
    matches: list[AgentModMatch],
) -> str:
    trace = _self_correction_trace(query_plan)
    if not _self_correction_blocks_direct(trace):
        return ""
    reason = _self_correction_reason(trace)
    lines = [
        "当前候选中没有足够明确的直接命中项。",
        "LLM Review 认为这些候选不能安全作为主推荐，因此不会把它们包装成直接推荐。",
    ]
    if reason:
        lines.append(f"原因：{reason}")
    if matches:
        lines.append("")
        lines.append("待复核候选（不作为主推荐）：")
        for index, match in enumerate(matches[:6], start=1):
            title = str(getattr(match, "title", "") or "未命名候选").strip()
            category = str(getattr(match, "category", "") or "").strip()
            summary = str(getattr(match, "summary", "") or getattr(match, "original_summary", "") or "").strip()
            details = [title]
            if category:
                details.append(f"类型：{category}")
            if summary:
                details.append(f"摘要：{summary[:140]}")
            lines.append(f"{index}. " + "；".join(details))
    lines.append("")
    lines.append("建议继续细化检索词，或放宽目标后重新检索。")
    return "\n".join(lines)


def _self_correction_trace(query_plan: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(query_plan, dict):
        return {}
    value = query_plan.get("_agent_self_correction_trace")
    return value if isinstance(value, dict) else {}


def _self_correction_blocks_direct(trace: dict[str, Any]) -> bool:
    if not trace:
        return False
    final_status = str(trace.get("final_status") or "").strip().lower()
    if final_status == "llm_review_unavailable":
        return False
    if final_status in {"fallback", "clarification_needed"}:
        return True
    rounds = trace.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        return False
    last_round = rounds[-1] if isinstance(rounds[-1], dict) else {}
    action = str(last_round.get("action") or "").strip().lower()
    review_status = str(last_round.get("review_status") or "").strip().lower()
    if action == "fallback_no_direct_match":
        return True
    return review_status in {"invalid", "blocked"} and action != "continue_answer"


def _self_correction_reason(trace: dict[str, Any]) -> str:
    rounds = trace.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        return ""
    last_round = rounds[-1] if isinstance(rounds[-1], dict) else {}
    reason = str(last_round.get("reason_summary") or "").strip()
    gaps = last_round.get("gaps")
    if isinstance(gaps, list):
        gap_text = "；".join(str(item or "").strip() for item in gaps[:3] if str(item or "").strip())
        if gap_text:
            return f"{reason}；{gap_text}" if reason else gap_text
    return reason[:500]


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in values:
            values.append(text)
    return values[:8]


def _fallback_answer_for_intent(intent: object, matches: list[AgentModMatch], query_plan: dict[str, Any] | None = None) -> str:
    contract_answer = build_contract_fallback_answer(matches, query_plan)
    if contract_answer != build_fallback_answer(matches):
        return contract_answer
    if intent == "install_risk":
        return build_install_risk_fallback(matches)
    if intent == "comparison":
        return build_comparison_fallback(matches)
    if intent == "alternative":
        return build_alternative_fallback(matches)
    if intent == "preference_summary":
        return build_recommendation_fallback(matches)
    return build_fallback_answer(matches)

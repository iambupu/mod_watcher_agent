# 中文注释：规范化 Agent 查询计划、槽位约束和语义信号。

from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from app.services.agent.planning.context_memory_selection import (
    diagnosis_context_from_last_query,
    select_effective_last_query_context,
)
from app.services.agent.planning.context_query_plan import build_context_query_plan


@dataclass(frozen=True)
class ContextPlanningOutput:
    query_plan: dict[str, Any]
    effective_last_query_context: dict[str, Any]
    diagnosis_context_keywords: list[str]
    diagnosis_context_slots: dict[str, Any]


def prepare_contextual_query_plan(
    *,
    query: str,
    active_constraints: dict[str, Any] | None,
    last_query_context: dict[str, Any] | None,
    shown_mod_titles: list[str] | None,
    history: list | None,
    memory_context: dict[str, Any] | None,
    session: Session | None,
    evidence_id: str,
) -> ContextPlanningOutput:
    effective_last_query_context = select_effective_last_query_context(
        query,
        last_query_context,
        memory_context,
    )
    query_plan = build_context_query_plan(
        query,
        active_constraints,
        effective_last_query_context,
        shown_mod_titles,
        history,
        session,
    )
    query_plan["evidence_id"] = evidence_id
    diagnosis_context_keywords, diagnosis_context_slots = diagnosis_context_from_last_query(
        effective_last_query_context,
        history,
    )
    context_signal = query_plan.get("_agent_context_signal")
    if isinstance(context_signal, dict):
        diagnosis_context_slots = {**diagnosis_context_slots, "_agent_context_signal": context_signal}
    return ContextPlanningOutput(
        query_plan=query_plan,
        effective_last_query_context=effective_last_query_context,
        diagnosis_context_keywords=diagnosis_context_keywords,
        diagnosis_context_slots=diagnosis_context_slots,
    )

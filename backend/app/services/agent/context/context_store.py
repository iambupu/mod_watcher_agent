# 中文注释：维护 Agent 多轮上下文的选择、窗口和持久化边界。

from typing import NotRequired, TypedDict


class AgentContextSnapshot(TypedDict):
    running_summary: str
    recent_messages: list
    active_constraints: dict[str, object]
    last_query_context: NotRequired[dict[str, object]]
    shown_mod_titles: NotRequired[list[str]]
    tool_traces: list
    reflection_notes: list
    summary_updated_at: NotRequired[str | None]


def empty_context_snapshot() -> AgentContextSnapshot:
    return {
        "running_summary": "",
        "recent_messages": [],
        "active_constraints": {},
        "last_query_context": {},
        "shown_mod_titles": [],
        "tool_traces": [],
        "reflection_notes": [],
        "summary_updated_at": None,
    }

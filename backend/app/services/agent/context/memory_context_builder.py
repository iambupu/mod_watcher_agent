# 中文注释：维护 Agent 多轮上下文的选择、窗口和持久化边界。

from typing import Any

from sqlmodel import Session

from app.services.agent.tools.memory_context_tool import MemoryContextInput, MemoryContextTool


def load_agent_memory_context(
    *,
    session: Session | None,
    last_query_context: dict[str, Any] | None,
    active_constraints: dict[str, Any] | None,
    shown_mod_titles: list[str] | None,
    evidence_id: str = "",
) -> dict[str, Any]:
    short_term = {
        "last_query_context": last_query_context or {},
        "active_constraints": active_constraints or {},
        "shown_mod_titles": shown_mod_titles or [],
    }
    return MemoryContextTool(session).run(MemoryContextInput(short_term=short_term, evidence_id=evidence_id))

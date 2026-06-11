# 中文注释：维护 Agent 多轮上下文的选择、窗口和持久化边界。

from typing import Any

from app.services.agent.schemas import AgentChatRequest, AgentModDetailRequest
from app.services.agent.tools.context_summary_tool import ContextSummaryTool


def build_context_state_update(
    request: AgentChatRequest | AgentModDetailRequest,
    *,
    evidence_id: str,
) -> dict[str, Any]:
    context = ContextSummaryTool().run(request, evidence_id=evidence_id)
    return {
        "running_summary": context["running_summary"],
        "active_constraints": context["active_constraints"],
        "last_query_context": context.get("last_query_context", {}),
        "shown_mod_titles": context.get("shown_mod_titles", []),
        "tool_traces": context["tool_traces"],
        "reflection_notes": context["reflection_notes"],
        "context_snapshot": context,
    }

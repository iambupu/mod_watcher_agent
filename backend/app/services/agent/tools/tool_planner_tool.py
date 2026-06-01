import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.planning.tool_planner import (
    ToolPlan,
    build_tool_plan,
    default_tool_capabilities,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolPlannerInput:
    query_diagnosis: dict[str, Any]
    preferences: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, bool] | None = None
    local_only: bool = False
    evidence_id: str = ""


class ToolPlannerTool:
    """根据诊断结果选择本地和在线检索工具，并记录可解释降级原因。"""

    name = "tool_planner"

    def run(self, tool_input: ToolPlannerInput) -> ToolPlan:
        capabilities = (
            tool_input.capabilities
            if tool_input.capabilities is not None
            else default_tool_capabilities()
        )
        tool_plan = build_tool_plan(
            query_diagnosis=tool_input.query_diagnosis,
            preferences=tool_input.preferences,
            capabilities=capabilities,
            local_only=tool_input.local_only,
        )
        logger.info(
            "agent.tool name=tool_planner status=succeeded groups=%s online_tools=%s degraded=%s tool_policy_score=%s tool_policy_strategy=%s online_recall_mode=%s evidence_id=%s",
            [group["name"] for group in tool_plan.get("parallel_groups", [])],
            [step.get("tool") for step in tool_plan.get("online_steps", [])],
            tool_plan.get("degraded_reasons", []),
            (tool_plan.get("tool_policy_evidence") or {}).get("score"),
            (tool_plan.get("tool_policy_evidence") or {}).get("strategy"),
            (tool_plan.get("tool_policy_evidence") or {}).get("online_recall_mode"),
            tool_input.evidence_id,
        )
        return tool_plan

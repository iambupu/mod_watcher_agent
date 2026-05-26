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
    """Agent tool for selecting retrieval tools and fallback strategy."""

    name = "tool_planner"

    def run(self, tool_input: ToolPlannerInput) -> ToolPlan:
        capabilities = (
            tool_input.capabilities
            if tool_input.capabilities is not None
            else default_tool_capabilities()
        )
        if not capabilities.get("qdrant_vector"):
            logger.info("agent.vector status=degraded reason=qdrant_disabled")
        tool_plan = build_tool_plan(
            query_diagnosis=tool_input.query_diagnosis,
            preferences=tool_input.preferences,
            capabilities=capabilities,
            local_only=tool_input.local_only,
        )
        logger.info(
            "agent.tool name=tool_planner status=succeeded groups=%s fallback_tools=%s degraded=%s strategy=%s conservative_mode=%s evidence_id=%s",
            [group["name"] for group in tool_plan.get("parallel_groups", [])],
            [step.get("tool") for step in tool_plan.get("fallback_steps", [])],
            tool_plan.get("degraded_reasons", []),
            (tool_plan.get("planning_evidence") or {}).get("strategy"),
            (tool_plan.get("planning_evidence") or {}).get("conservative_mode"),
            tool_input.evidence_id,
        )
        return tool_plan

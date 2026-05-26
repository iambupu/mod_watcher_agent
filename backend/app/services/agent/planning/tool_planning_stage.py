import logging
from typing import Any

from app.services.agent.planning.tool_plan_merge import apply_tool_plan_to_query_plan
from app.services.agent.tools.tool_planner_tool import ToolPlannerInput, ToolPlannerTool

logger = logging.getLogger(__name__)


def plan_retrieval_tools(
    *,
    query_diagnosis: dict[str, Any],
    preferences: dict[str, Any],
    query_plan: dict[str, Any] | None,
    evidence_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tool_plan = ToolPlannerTool().run(
        ToolPlannerInput(
            query_diagnosis=query_diagnosis,
            preferences=preferences,
            local_only=False,
            evidence_id=evidence_id,
        )
    )
    logger.info(
        "agent.tool_plan groups=%s fallback_tools=%s degraded=%s planning_score=%s planning_strategy=%s conservative_mode=%s evidence_id=%s",
        [group["name"] for group in tool_plan.get("parallel_groups", [])],
        [step.get("tool") for step in tool_plan.get("fallback_steps", [])],
        tool_plan.get("degraded_reasons", []),
        (tool_plan.get("planning_evidence") or {}).get("score"),
        (tool_plan.get("planning_evidence") or {}).get("strategy"),
        (tool_plan.get("planning_evidence") or {}).get("conservative_mode"),
        evidence_id,
    )
    return tool_plan, apply_tool_plan_to_query_plan(query_plan, tool_plan)

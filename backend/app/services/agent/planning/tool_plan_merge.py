from typing import Any


def apply_tool_plan_to_query_plan(query_plan: dict[str, Any] | None, tool_plan: dict[str, Any] | None) -> dict[str, Any]:
    """Apply planning-derived execution hints without exposing planner internals to the workflow graph."""
    merged = dict(query_plan or {})
    planning_evidence = tool_plan.get("planning_evidence") if isinstance(tool_plan, dict) else {}
    if isinstance(planning_evidence, dict):
        merged["_agent_conservative_mode"] = bool(planning_evidence.get("conservative_mode"))
    return merged

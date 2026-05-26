from typing import Any

from app.services.agent.planning.tool_planner import ALLOWED_TOOLS


def critique_plan(tool_plan: dict[str, Any]) -> dict[str, Any]:
    tools = [step.get("tool") for step in tool_plan.get("steps", []) if isinstance(step, dict)]
    unknown = [tool for tool in tools if tool not in ALLOWED_TOOLS]
    if unknown:
        return {
            "stage": "plan_critic",
            "confidence": 0.2,
            "issues": ["工具计划包含未授权工具"],
            "actions": [{"type": "answer_with_limitations", "target": "tool_plan", "reason": "工具白名单校验失败"}],
            "public_summary": "工具白名单校验未通过，已阻止未授权工具执行。",
        }
    return {
        "stage": "plan_critic",
        "confidence": 0.9,
        "issues": [],
        "actions": [],
        "public_summary": "工具计划已通过白名单和策略检查。",
    }

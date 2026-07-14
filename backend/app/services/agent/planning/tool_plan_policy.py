from typing import Any

ONLINE_TOOL_NAMES = frozenset(
    {"nexusmods_search", "loverslab_google", "loverslab_scrape", "web_search"}
)


def planned_tools(tool_plan: dict[str, Any]) -> set[str]:
    tools: set[str] = set()
    for group in tool_plan.get("parallel_groups") or []:
        if not isinstance(group, dict):
            continue
        tools.update(
            str(tool).strip() for tool in (group.get("tools") or []) if str(tool).strip()
        )
    for step in tool_plan.get("online_steps") or []:
        if isinstance(step, dict) and str(step.get("tool") or "").strip():
            tools.add(str(step.get("tool")).strip())
    return tools


def online_recall_mode(tool_plan: dict[str, Any]) -> str:
    policy = tool_plan.get("tool_policy_evidence") if isinstance(tool_plan, dict) else {}
    if not isinstance(policy, dict):
        return "broad"
    mode = str(policy.get("online_recall_mode") or "").strip()
    return mode if mode in {"narrow", "broad"} else "broad"


def allowed_online_tools(tool_names: set[str]) -> set[str]:
    allowed = tool_names & ONLINE_TOOL_NAMES
    if "web_search" in allowed:
        return {"nexusmods_search", "loverslab_google", "loverslab_scrape"}
    if "loverslab_google" in allowed:
        allowed.add("loverslab_scrape")
    return allowed

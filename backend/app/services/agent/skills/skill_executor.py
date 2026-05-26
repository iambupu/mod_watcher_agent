from typing import Any

from app.services.agent.skills.skill_registry import AgentSkill, AgentSkillResult


async def execute_skill(
    skill: AgentSkill,
    *,
    allowed_tools: set[str],
    payload: dict[str, Any],
) -> AgentSkillResult:
    usable_tools = [tool for tool in skill.allowed_tools if tool in allowed_tools]
    if not usable_tools:
        return AgentSkillResult(
            answer_payload={},
            matches=[],
            trace={"skill": skill.name, "status": "blocked", "reason": "no allowed tools"},
            confidence=0,
            followup_questions=[],
        )
    return AgentSkillResult(
        answer_payload={"query": payload.get("query"), "skill": skill.name},
        matches=[],
        trace={"skill": skill.name, "status": "succeeded", "tools": usable_tools},
        confidence=0.7,
        followup_questions=[],
    )

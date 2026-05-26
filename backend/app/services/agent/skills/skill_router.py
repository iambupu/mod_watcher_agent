from typing import Any

from app.services.agent.skills.skill_registry import AgentSkill, get_builtin_skill


def route_skills(*, query: str, query_diagnosis: dict[str, Any]) -> list[AgentSkill]:
    intent = str(query_diagnosis.get("intent") or "").lower()
    lowered = query.lower()
    if intent == "comparison" or any(
        marker in lowered for marker in ["哪个", "哪一个", "对比", "比较", "更适合", "which", "compare", "better"]
    ):
        return [get_builtin_skill("comparison_research")]
    if intent == "alternative" or any(
        marker in lowered for marker in ["替代", "平替", "换一个", "更稳", "alternative", "replacement", "safer"]
    ):
        return [get_builtin_skill("alternative_research")]
    if any(marker in lowered for marker in ["风险", "安装", "前置", "兼容"]):
        return [get_builtin_skill("install_risk")]
    if any(marker in lowered for marker in ["偏好", "收藏", "喜欢"]):
        return [get_builtin_skill("preference_summary")]
    if intent in {"search", "recent", "game"} or any(marker in lowered for marker in ["找", "推荐", "research"]):
        return [get_builtin_skill("mod_research")]
    return []

import pytest

from app.services.agent.skills.skill_executor import execute_skill
from app.services.agent.skills.skill_registry import get_builtin_skill, list_builtin_skills
from app.services.agent.skills.skill_router import route_skills


def test_builtin_skills_declare_allowed_tools_and_contracts():
    skills = list_builtin_skills()

    assert {
        "mod_research",
        "comparison_research",
        "alternative_research",
        "install_risk",
        "preference_summary",
    }.issubset(skills)
    research = get_builtin_skill("mod_research")
    assert "sqlite_fts" in research.allowed_tools
    assert research.output_contract == "AgentSkillResult"


def test_skill_router_selects_mod_research_for_search_intent():
    routed = route_skills(
        query="帮我找 Stellar Blade 服装 Mod",
        query_diagnosis={"intent": "search", "known_slots": {"game": "Stellar Blade"}},
    )

    assert [skill.name for skill in routed] == ["mod_research"]


def test_skill_router_selects_install_risk_for_diagnosed_risk_intent():
    routed = route_skills(
        query="这个安装风险高吗",
        query_diagnosis={"intent": "install_risk", "known_slots": {}},
    )

    assert [skill.name for skill in routed] == ["install_risk"]


def test_skill_router_selects_alternative_research_for_replacement_intent():
    routed = route_skills(
        query="有没有更稳的替代品",
        query_diagnosis={"intent": "alternative", "known_slots": {"game": "Skyrim Special Edition"}},
    )

    assert [skill.name for skill in routed] == ["alternative_research"]


def test_skill_router_selects_comparison_research_for_decision_intent():
    routed = route_skills(
        query="这两个哪个更适合新手",
        query_diagnosis={"intent": "comparison", "known_slots": {}},
    )

    assert [skill.name for skill in routed] == ["comparison_research"]


@pytest.mark.asyncio
async def test_skill_executor_enforces_tool_whitelist():
    skill = get_builtin_skill("mod_research")

    result = await execute_skill(
        skill,
        allowed_tools={"structured_sql", "sqlite_fts"},
        payload={"query": "Stellar Blade outfit"},
    )

    assert result.confidence > 0
    assert result.trace["skill"] == "mod_research"
    assert result.trace["tools"] == ["structured_sql", "sqlite_fts"]

    blocked = await execute_skill(skill, allowed_tools={"unsafe_url_fetch"}, payload={"query": "x"})
    assert blocked.confidence == 0
    assert blocked.trace["status"] == "blocked"

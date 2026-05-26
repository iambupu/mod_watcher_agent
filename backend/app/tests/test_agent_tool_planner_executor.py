import asyncio

import pytest

from app.services.agent.planning.parallel_executor import execute_tool_group
from app.services.agent.planning.tool_planner import build_tool_plan
from app.services.agent.tools.tool_planner_tool import ToolPlannerInput, ToolPlannerTool


def test_tool_planner_builds_local_first_plan_and_online_fallback():
    plan = build_tool_plan(
        query_diagnosis={"known_slots": {"source": "nexusmods"}, "should_clarify": False},
        preferences={"favorite_summary": {"top_sources": ["nexusmods"]}},
        capabilities={"nexusmods_search": True, "loverslab_google": False, "qdrant_vector": False},
        local_only=False,
    )

    assert [step["tool"] for step in plan["steps"][:2]] == ["structured_sql", "sqlite_fts"]
    assert any(step["tool"] == "nexusmods_search" for step in plan["fallback_steps"])
    assert plan["parallel_groups"][0]["name"] == "local_retrieval"
    assert "qdrant_vector" not in plan["parallel_groups"][0]["tools"]
    assert isinstance(plan["planning_evidence"]["score"], float)
    assert plan["planning_evidence"]["strategy"] == "local_first_with_online_fallback"


def test_tool_planner_blocks_online_tools_in_local_only_mode():
    plan = build_tool_plan(
        query_diagnosis={"known_slots": {"source": "nexusmods"}, "should_clarify": False},
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
        local_only=True,
    )

    all_tools = [step["tool"] for step in [*plan["steps"], *plan["fallback_steps"]]]
    assert "nexusmods_search" not in all_tools
    assert "loverslab_google" not in all_tools
    assert any("local-only" in item for item in plan["degraded_reasons"])
    assert plan["planning_evidence"]["strategy"] == "local_only"


def test_tool_planner_uses_conservative_online_mode_for_low_confidence_ambiguous_query():
    plan = build_tool_plan(
        query_diagnosis={"known_slots": {}, "should_clarify": True, "confidence": 0.3},
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
        local_only=False,
    )

    fallback_tools = [step["tool"] for step in plan["fallback_steps"]]
    assert fallback_tools == ["nexusmods_search"]
    assert any("在线阶段先收窄到 nexusmods_search" in item for item in plan["degraded_reasons"])
    assert plan["planning_evidence"]["conservative_mode"] is True
    assert plan["planning_evidence"]["expand_online_candidates"] == ["loverslab_google"]


def test_tool_planner_disables_conservative_mode_for_source_scope_semantic_domain():
    plan = build_tool_plan(
        query_diagnosis={
            "known_slots": {},
            "should_clarify": True,
            "confidence": 0.2,
            "understanding": {
                "evidence": [
                    {"field": "semantic_anchors", "value": ["framework", "loverslab"]},
                    {"field": "semantic_domains", "value": ["source_scope", "content_type"]},
                ]
            },
        },
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
        local_only=False,
    )

    fallback_tools = [step["tool"] for step in plan["fallback_steps"]]
    assert "loverslab_google" in fallback_tools
    assert plan["planning_evidence"]["conservative_mode"] is False
    assert plan["planning_evidence"]["semantic_domains"] == ["source_scope", "content_type"]


def test_tool_planner_prefers_loverslab_when_framework_anchor_present():
    plan = build_tool_plan(
        query_diagnosis={
            "known_slots": {},
            "should_clarify": False,
            "confidence": 0.7,
            "understanding": {
                "evidence": [
                    {"field": "semantic_anchors", "value": ["framework"]},
                    {"field": "semantic_domains", "value": ["content_type"]},
                ]
            },
        },
        preferences={},
        capabilities={"nexusmods_search": False, "loverslab_google": True},
        local_only=False,
    )

    fallback_tools = [step["tool"] for step in plan["fallback_steps"]]
    assert fallback_tools == ["loverslab_google"]


def test_tool_planner_tool_matches_planner_contract():
    planner_input = ToolPlannerInput(
        query_diagnosis={"known_slots": {"source": "nexusmods"}, "should_clarify": False},
        preferences={"favorite_summary": {"top_sources": ["nexusmods"]}},
        capabilities={"nexusmods_search": True, "loverslab_google": False, "qdrant_vector": False},
        local_only=False,
    )

    via_tool = ToolPlannerTool().run(planner_input)
    direct = build_tool_plan(
        query_diagnosis=planner_input.query_diagnosis,
        preferences=planner_input.preferences,
        capabilities=planner_input.capabilities,
        local_only=planner_input.local_only,
    )

    assert via_tool == direct


def test_tool_planner_tool_uses_default_runtime_capabilities():
    planner_input = ToolPlannerInput(
        query_diagnosis={"known_slots": {}, "should_clarify": False, "confidence": 0.8},
        preferences={},
    )

    via_tool = ToolPlannerTool().run(planner_input)

    assert [step["tool"] for step in via_tool["fallback_steps"]] == ["nexusmods_search"]
    assert via_tool["planning_evidence"]["expand_online_candidates"] == ["loverslab_google"]
    assert "qdrant_vector" not in via_tool["parallel_groups"][0]["tools"]


@pytest.mark.asyncio
async def test_parallel_executor_isolates_exceptions_and_timeouts():
    async def ok_tool():
        await asyncio.sleep(0)
        return ["ok"]

    async def failed_tool():
        raise RuntimeError("secret failure")

    async def slow_tool():
        await asyncio.sleep(0.05)
        return ["slow"]

    result = await execute_tool_group(
        {
            "ok": ok_tool,
            "failed": failed_tool,
            "slow": slow_tool,
        },
        timeout_ms=1,
    )

    assert result["ok"].status == "succeeded"
    assert result["ok"].result == ["ok"]
    assert result["failed"].status == "failed"
    assert result["failed"].error_type == "RuntimeError"
    assert "secret failure" not in str(result["failed"].trace)
    assert result["slow"].status == "timeout"

import pytest

from app.models.mod import Mod
from app.services.agent.planning import tool_planner as tool_planner_module
from app.services.agent.planning.tool_planner import build_tool_plan
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.tools.tool_executor_tool import (
    ToolExecutorInput,
    ToolExecutorTool,
    _online_retrieval_decision,
)
from app.services.agent.tools.tool_planner_tool import ToolPlannerInput, ToolPlannerTool


def test_tool_planner_builds_local_first_plan_and_online_expansion():
    plan = build_tool_plan(
        query_diagnosis={"known_slots": {"source": "nexusmods"}, "should_clarify": False},
        preferences={"favorite_summary": {"top_sources": ["nexusmods"]}},
        capabilities={"nexusmods_search": True, "loverslab_google": False},
        local_only=False,
    )

    assert [step["tool"] for step in plan["steps"][:2]] == ["structured_sql", "sqlite_fts"]
    assert any(step["tool"] == "nexusmods_search" for step in plan["online_steps"])
    assert plan["parallel_groups"][0]["name"] == "local_retrieval"
    assert isinstance(plan["tool_policy_evidence"]["score"], float)
    assert plan["tool_policy_evidence"]["strategy"] == "local_first_with_online"


def test_tool_planner_tolerates_invalid_diagnosis_confidence():
    plan = build_tool_plan(
        query_diagnosis={"confidence": "bad", "known_slots": {}, "should_clarify": False},
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
    )

    assert plan["steps"]


def test_tool_planner_treats_string_false_should_clarify_as_false():
    plan = build_tool_plan(
        query_diagnosis={"known_slots": {}, "should_clarify": "false", "confidence": 0.3},
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
    )
    baseline = build_tool_plan(
        query_diagnosis={"known_slots": {}, "should_clarify": False, "confidence": 0.3},
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
    )

    assert plan["online_steps"] == baseline["online_steps"]


def test_search_plan_roundtrip_preserves_negative_filter_fields():
    query_plan = {
        "keywords": ["bimbo", "preset"],
        "excluded_sources": ["loverslab"],
        "exclude_titles": ["Blocked Bimbo"],
        "keyword_match_mode": "all",
        "limit": 8,
    }

    roundtrip = SearchPlan.from_query_plan(query_plan).to_query_plan()

    assert roundtrip["excluded_sources"] == ["loverslab"]
    assert roundtrip["exclude_titles"] == ["Blocked Bimbo"]
    assert roundtrip["keyword_match_mode"] == "all"


def test_tool_planner_blocks_online_tools_in_local_only_mode():
    plan = build_tool_plan(
        query_diagnosis={"known_slots": {"source": "nexusmods"}, "should_clarify": False},
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
        local_only=True,
    )

    all_tools = [step["tool"] for step in [*plan["steps"], *plan["online_steps"]]]
    assert "nexusmods_search" not in all_tools
    assert "loverslab_google" not in all_tools
    assert any("local-only" in item for item in plan["degraded_reasons"])
    assert plan["tool_policy_evidence"]["strategy"] == "local_only"


def test_tool_planner_uses_narrow_online_recall_for_low_confidence_ambiguous_query():
    plan = build_tool_plan(
        query_diagnosis={"known_slots": {}, "should_clarify": True, "confidence": 0.3},
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
        local_only=False,
    )

    online_tools = [step["tool"] for step in plan["online_steps"]]
    assert online_tools == ["nexusmods_search"]
    assert any("在线阶段先收窄到 nexusmods_search" in item for item in plan["degraded_reasons"])
    assert plan["tool_policy_evidence"]["online_recall_mode"] == "narrow"
    assert plan["tool_policy_evidence"]["expand_online_candidates"] == ["loverslab_google"]


def test_tool_planner_uses_broad_online_recall_for_source_scope_semantic_domain():
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

    online_tools = [step["tool"] for step in plan["online_steps"]]
    assert "loverslab_google" in online_tools
    assert plan["tool_policy_evidence"]["online_recall_mode"] == "broad"
    assert plan["tool_policy_evidence"]["semantic_domains"] == ["source_scope", "content_type"]


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

    online_tools = [step["tool"] for step in plan["online_steps"]]
    assert online_tools == ["loverslab_google"]


def test_tool_planner_keeps_broad_online_sources_for_semantic_content_queries():
    plan = build_tool_plan(
        query_diagnosis={
            "known_slots": {"game": "Skyrim Special Edition"},
            "should_clarify": False,
            "confidence": 0.75,
            "understanding": {
                "evidence": [
                    {"field": "semantic_anchors", "value": ["bimbo", "roleplay"]},
                    {"field": "semantic_domains", "value": ["identity_style", "mechanics", "content_type"]},
                ]
            },
        },
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
        local_only=False,
    )

    online_tools = [step["tool"] for step in plan["online_steps"]]
    assert online_tools == ["nexusmods_search", "loverslab_google"]


def test_tool_planner_respects_explicit_source_constraint_for_online_sources():
    plan = build_tool_plan(
        query_diagnosis={
            "known_slots": {"source": "loverslab"},
            "should_clarify": False,
            "confidence": 0.8,
            "understanding": {
                "evidence": [
                    {"field": "semantic_anchors", "value": ["roleplay"]},
                    {"field": "semantic_domains", "value": ["mechanics", "content_type"]},
                ]
            },
        },
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
        local_only=False,
    )

    online_tools = [step["tool"] for step in plan["online_steps"]]
    assert online_tools == ["loverslab_google"]


def test_tool_planner_uses_semantic_strategy_as_tool_policy():
    semantic_strategy = {
        "task_type": "open_discovery",
        "strategy": "broad_then_judge",
        "hard_filters": {},
    }
    plan = build_tool_plan(
        query_diagnosis={
            "known_slots": {},
            "should_clarify": True,
            "confidence": 0.2,
            "understanding": {"evidence": [{"field": "semantic_strategy", "value": semantic_strategy}]},
        },
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
        local_only=False,
    )

    assert [step["tool"] for step in plan["online_steps"]] == ["nexusmods_search", "loverslab_google"]
    assert plan["tool_policy_evidence"]["strategy"] == "open_discovery_broad_recall_policy"
    assert plan["tool_policy_evidence"]["execution_strategy"] == "local_first_with_online"
    assert plan["tool_policy_evidence"]["tool_policy"] == "open_discovery_broad_recall_policy"
    assert plan["tool_policy_evidence"]["online_recall_mode"] == "broad"


def test_tool_planner_normalizes_semantic_strategy_source_aliases():
    semantic_strategy = {
        "task_type": "open_discovery",
        "strategy": "broad_then_judge",
        "hard_filters": {"source": "LL"},
    }
    plan = build_tool_plan(
        query_diagnosis={
            "known_slots": {},
            "should_clarify": False,
            "confidence": 0.8,
            "understanding": {"evidence": [{"field": "semantic_strategy", "value": semantic_strategy}]},
        },
        preferences={},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
        local_only=False,
    )

    assert [step["tool"] for step in plan["online_steps"]] == ["loverslab_google"]


def test_tool_planner_preference_strategy_avoids_online_expansion():
    semantic_strategy = {
        "task_type": "preference",
        "strategy": "memory_summary",
        "hard_filters": {},
    }
    plan = build_tool_plan(
        query_diagnosis={
            "known_slots": {},
            "should_clarify": False,
            "confidence": 0.9,
            "understanding": {"evidence": [{"field": "semantic_strategy", "value": semantic_strategy}]},
        },
        preferences={"favorite_summary": {"top_sources": ["nexusmods"]}},
        capabilities={"nexusmods_search": True, "loverslab_google": True},
        local_only=False,
    )

    assert plan["online_steps"] == []
    assert plan["tool_policy_evidence"]["strategy"] == "preference_memory_policy"


def test_tool_planner_filters_parallel_groups_from_whitelisted_steps(monkeypatch):
    monkeypatch.setattr(
        tool_planner_module,
        "_tool_policy_for_semantic_strategy",
        lambda strategy: {
            "strategy": "test_invalid_policy",
            "online_tools": ["nexusmods_search", "unknown_online_tool"],
            "online_recall_mode": "broad",
        },
    )
    plan = build_tool_plan(
        query_diagnosis={
            "known_slots": {},
            "should_clarify": False,
            "confidence": 0.9,
            "understanding": {"evidence": [{"field": "semantic_strategy", "value": {"task_type": "open_discovery"}}]},
        },
        preferences={},
        capabilities={"nexusmods_search": True, "unknown_online_tool": True},
        local_only=False,
    )

    group_tools = {tool for group in plan["parallel_groups"] for tool in group["tools"]}
    assert [step["tool"] for step in plan["online_steps"]] == ["nexusmods_search"]
    assert "unknown_online_tool" not in group_tools


def test_tool_planner_tool_matches_planner_contract():
    planner_input = ToolPlannerInput(
        query_diagnosis={"known_slots": {"source": "nexusmods"}, "should_clarify": False},
        preferences={"favorite_summary": {"top_sources": ["nexusmods"]}},
        capabilities={"nexusmods_search": True, "loverslab_google": False},
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

    assert [step["tool"] for step in via_tool["online_steps"]] == ["nexusmods_search"]
    assert via_tool["tool_policy_evidence"]["expand_online_candidates"] == ["loverslab_google"]


@pytest.mark.asyncio
async def test_tool_executor_runs_dual_local_retrieval_and_marks_branches(monkeypatch):
    async def fake_local_run(self, tool_input):
        keywords = tool_input.plan.keywords
        if keywords == ["sexism"]:
            return [
                SearchResult(
                    score=7,
                    tool_name="local_db_search",
                    mod=Mod(
                        source="loverslab",
                        external_id="sexism-2",
                        game="Skyrim Special Edition",
                        title="Vanilla Sexism 2",
                        url="https://example.com/sexism-2",
                    ),
                )
            ]
        if keywords == ["bimbo"]:
            return [
                SearchResult(
                    score=9,
                    tool_name="local_db_search",
                    mod=Mod(
                        source="loverslab",
                        external_id="bimbo-1",
                        game="Skyrim Special Edition",
                        title="Bimbo Roleplay",
                        url="https://example.com/bimbo-1",
                    ),
                )
            ]
        return []

    monkeypatch.setattr(
        "app.services.agent.tools.tool_executor_tool.LocalDbSearchTool.run",
        fake_local_run,
    )
    output = await ToolExecutorTool(session=None).run(
        ToolExecutorInput(
            query="性别歧视主题的 mod",
            query_plan={
                "keywords": ["bimbo"],
                "sort_field": "relevance",
                "sort_order": "desc",
                "limit": 4,
                "_agent_current_only_plan": {
                    "keywords": ["sexism"],
                    "sort_field": "relevance",
                    "sort_order": "desc",
                    "limit": 4,
                },
                "_agent_dual_retrieval": {"enabled": True, "reason": "fallback_keywords"},
            },
            tool_plan={"parallel_groups": [{"tools": ["local_db_search"]}], "online_steps": []},
            evidence_id="ev_dual",
        )
    )

    assert [item.retrieval_branch for item in output.staged_results] == ["current_only", "context_scoped"]
    assert [item.mod.title for item in output.staged_results] == ["Vanilla Sexism 2", "Bimbo Roleplay"]
    summary = next(item for item in output.evidence if item.get("retrieval_branch") == "dual_summary")
    assert summary["current_only_count"] == 1
    assert summary["context_scoped_count"] == 1
    assert summary["current_only_reserved"] == 1


def test_online_gate_queries_for_open_discovery_even_with_local_results():
    local_result = SearchResult(
        score=3,
        tool_name="local_db_search",
        mod=Mod(
            source="nexusmods",
            external_id="local-1",
            game="Skyrim Special Edition",
            title="Local Bimbo Preset",
            url="https://example.com/local",
            category="Body",
            first_seen_at="2026-05-28T00:00:00+00:00",
            last_seen_at="2026-05-28T00:00:00+00:00",
            original_summary="A local preset.",
        ),
    )

    decision = _online_retrieval_decision(
        query_plan={"keywords": ["bimbo"], "open_discovery": True, "retrieval_mode": "fuzzy"},
        query="天际有什么扮演bimbo的MOD",
        local_results=[local_result],
        online_allowed=True,
    )

    assert decision.should_query is True
    assert "open_discovery_query" in decision.reasons
    assert "local_results_too_few" in decision.reasons


def test_online_gate_does_not_treat_filtered_open_query_as_fuzzy_discovery():
    local_results = [
        SearchResult(
            score=3,
            tool_name="local_db_search",
            mod=Mod(
                source=source,
                external_id=f"local-{index}",
                game="Skyrim Special Edition",
                title=f"Local Mod {index}",
                url=f"https://example.com/local-{index}",
                category="Body",
                first_seen_at="2026-05-28T00:00:00+00:00",
                last_seen_at="2026-05-28T00:00:00+00:00",
                original_summary="A local candidate with enough summary text.",
            ),
        )
        for index, source in enumerate(["nexusmods", "loverslab", "nexusmods"], start=1)
    ]

    decision = _online_retrieval_decision(
        query_plan={"keywords": ["mod"], "open_discovery": True, "retrieval_mode": "filtered"},
        query="有什么mod",
        local_results=local_results,
        online_allowed=True,
    )

    assert "open_discovery_query" not in decision.reasons
    assert decision.should_query is False
    assert decision.reason == "local_matches_sufficient"


def test_online_gate_skips_when_not_planned():
    decision = _online_retrieval_decision(
        query_plan={"keywords": ["bimbo"]},
        query="bimbo",
        local_results=[],
        online_allowed=False,
    )

    assert decision.should_query is False
    assert decision.reason == "not_planned"

# 中文注释：说明 backend/app/tests/test_agent_result_fusion_ranker_tool.py 的模块职责，便于后续维护定位。

from app.models.mod import Mod
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.tools.result_fusion_ranker_tool import (
    ResultFusionRankerInput,
    ResultFusionRankerTool,
)


def _result(
    title: str,
    external_id: str,
    score: int,
    *,
    branch: str = "",
    source: str = "nexusmods",
    summary: str = "",
):
    mod = Mod(
        source=source,
        external_id=external_id,
        game="Skyrim Special Edition",
        game_domain="skyrimspecialedition",
        title=title,
        url=f"https://example.com/{external_id}",
        category="Body",
        adult_content=False,
        original_summary=summary,
    )
    return SearchResult(score=score, mod=mod, tool_name="test", retrieval_branch=branch)


def test_result_fusion_ranker_tool_filters_and_emits_evidence():
    plan = SearchPlan.from_query_plan(
        {
            "keywords": ["bimbo"],
            "games": ["Skyrim Special Edition"],
            "categories": ["Body"],
            "adult_content": False,
            "sort_field": "relevance",
            "sort_order": "desc",
            "limit": 8,
        }
    )

    output = ResultFusionRankerTool().run(
        ResultFusionRankerInput(
            query="Skyrim bimbo body mod",
            query_plan=plan.to_query_plan(),
            plan=plan,
            staged_results=[
                _result("Bimbo Body Morph", "bimbo-1", 8),
                _result("Realistic Armor Overhaul", "armor-1", 12),
            ],
            online_results=[],
            evidence_id="ev_test",
        )
    )

    assert [item.mod.title for item in output.results] == ["Bimbo Body Morph"]
    assert output.evidence == [
        {
            "fragment_id": "r_fusion_1",
            "stage": "final_ranking",
            "tool": "result_fusion_ranker",
            "status": "succeeded",
            "count": 1,
            "evidence_id": "ev_test",
            "fields": ["sort_field", "sort_order", "limit"],
        }
    ]


def test_result_fusion_ranker_tool_can_skip_distinctive_filter_for_retry_sort_modes():
    plan = SearchPlan.from_query_plan(
        {
            "keywords": [],
            "sort_field": "updated_at_remote",
            "sort_order": "desc",
            "limit": 8,
        }
    )

    output = ResultFusionRankerTool().run(
        ResultFusionRankerInput(
            query="unmatched distinctive terms",
            query_plan=plan.to_query_plan(),
            plan=plan,
            staged_results=[_result("Fallback Candidate", "fallback-1", 1)],
            online_results=[],
            emit_evidence=False,
            apply_distinctive_filter=False,
        )
    )

    assert [item.mod.title for item in output.results] == ["Fallback Candidate"]
    assert output.evidence == []


def test_result_fusion_ranker_reserves_current_only_results_when_context_branch_dominates():
    plan = SearchPlan.from_query_plan(
        {
            "keywords": ["bimbo"],
            "sort_field": "relevance",
            "sort_order": "desc",
            "limit": 4,
        }
    )
    query_plan = plan.to_query_plan()
    query_plan["_agent_dual_retrieval"] = {"enabled": True, "reason": "fallback_keywords"}
    query_plan["_agent_context_signal"] = {
        "context_hints": ["bimbo"],
        "blocked_terms": ["bimbo"],
    }

    output = ResultFusionRankerTool().run(
        ResultFusionRankerInput(
            query="性别歧视主题的 mod",
            query_plan=query_plan,
            plan=plan,
            staged_results=[
                _result(
                    "Vanilla Sexism 2",
                    "sexism-2",
                    3,
                    branch="current_only",
                    source="loverslab",
                    summary="Adds sexism themed dialogue and social rules.",
                ),
                _result("Bimbo Body Morph", "bimbo-1", 20, branch="context_scoped", summary="Bimbo preset."),
                _result("Bimbo Roleplay", "bimbo-2", 18, branch="context_scoped", summary="Bimbo gameplay."),
            ],
            online_results=[],
            evidence_id="ev_guard",
            apply_distinctive_filter=False,
        )
    )

    assert output.results[0].mod.title == "Vanilla Sexism 2"
    guard = query_plan["_agent_context_pollution_guard"]
    assert guard["triggered"] is True
    assert guard["reason"] == "context_hints_displaced_current_only"
    assert guard["current_only_count"] == 1
    assert guard["context_scoped_count"] == 2
    assert guard["current_only_reserved"] == 1
    assert output.evidence[0]["context_pollution_guard"]["triggered"] is True

from app.models.mod import Mod
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.tools.result_fusion_ranker_tool import (
    ResultFusionRankerInput,
    ResultFusionRankerTool,
)


def _result(title: str, external_id: str, score: int):
    mod = Mod(
        source="nexusmods",
        external_id=external_id,
        game="Skyrim Special Edition",
        game_domain="skyrimspecialedition",
        title=title,
        url=f"https://example.com/{external_id}",
        category="Body",
        adult_content=False,
    )
    return SearchResult(score=score, mod=mod, tool_name="test")


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

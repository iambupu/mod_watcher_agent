from app.models.mod import Mod
from app.services.agent.search_types import SearchPlan, SearchResult


def test_search_plan_from_query_plan_normalizes_defaults():
    plan = SearchPlan.from_query_plan(
        {
            "keywords": ["XXTB"],
            "sources": ["nexusmods"],
            "sort_field": "updated_at_remote",
            "sort_order": "desc",
            "limit": "8",
        }
    )

    assert plan.keywords == ["XXTB"]
    assert plan.sources == ["nexusmods"]
    assert plan.sort_field == "updated_at_remote"
    assert plan.sort_order == "desc"
    assert plan.limit == 8
    assert plan.adult_content is None


def test_search_result_keeps_tool_source_and_score():
    mod = Mod(source="nexusmods", external_id="1", game="Stellar Blade", title="XXTB", url="https://example.com")
    result = SearchResult(score=5, mod=mod, tool_name="local_db_search")

    assert result.score == 5
    assert result.mod.title == "XXTB"
    assert result.tool_name == "local_db_search"

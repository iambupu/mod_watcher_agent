# 中文注释：说明 backend/app/tests/test_agent_search_types.py 的模块职责，便于后续维护定位。

from app.models.mod import Mod
from app.services.agent.search_types import SearchPlan, SearchResult


def test_search_plan_from_query_plan_normalizes_defaults():
    plan = SearchPlan.from_query_plan(
        {
            "keywords": ["XXTB"],
            "excluded_sources": ["loverslab"],
            "exclude_titles": ["Old XXTB"],
            "keyword_match_mode": "all",
            "tags": ["CBBE"],
            "summary_languages": ["zh-CN"],
            "requirement_terms": ["SKSE"],
            "compatibility_terms": ["AE"],
            "exact_title": "XXTB Outfit",
            "version": "1.2.0",
            "external_id": "1001",
            "source_url": "https://www.nexusmods.com/skyrimspecialedition/mods/1001",
            "has_thumbnail": True,
            "sources": ["nexusmods"],
            "sort_field": "updated_at_remote",
            "sort_order": "desc",
            "limit": "8",
        }
    )

    assert plan.keywords == ["XXTB"]
    assert plan.excluded_keywords == []
    assert plan.excluded_sources == ["loverslab"]
    assert plan.exclude_titles == ["Old XXTB"]
    assert plan.keyword_match_mode == "all"
    assert plan.tags == ["CBBE"]
    assert plan.summary_languages == ["zh-CN"]
    assert plan.requirement_terms == ["SKSE"]
    assert plan.compatibility_terms == ["AE"]
    assert plan.exact_title == "XXTB Outfit"
    assert plan.version == "1.2.0"
    assert plan.external_id == "1001"
    assert plan.source_url == "https://www.nexusmods.com/skyrimspecialedition/mods/1001"
    assert plan.has_thumbnail is True
    assert plan.sources == ["nexusmods"]
    assert plan.author is None
    assert plan.sort_field == "updated_at_remote"
    assert plan.sort_order == "desc"
    assert plan.limit == 8
    assert plan.adult_content is None
    assert plan.to_query_plan()["excluded_sources"] == ["loverslab"]
    assert plan.to_query_plan()["exclude_titles"] == ["Old XXTB"]
    assert plan.to_query_plan()["keyword_match_mode"] == "all"


def test_search_plan_from_query_plan_carries_author_filter():
    plan = SearchPlan.from_query_plan({"author": "Ousnius", "keywords": ["body"], "limit": 8})

    assert plan.author == "Ousnius"
    assert plan.to_query_plan()["author"] == "Ousnius"


def test_search_plan_from_query_plan_carries_source_identity_filters():
    plan = SearchPlan.from_query_plan(
        {
            "external_id": 48837,
            "source_url": "https://www.loverslab.com/files/file/48837-example/",
            "sources": ["loverslab"],
            "limit": 8,
        }
    )

    assert plan.external_id == "48837"
    assert plan.source_url == "https://www.loverslab.com/files/file/48837-example/"
    assert plan.to_query_plan()["external_id"] == "48837"
    assert plan.to_query_plan()["source_url"] == "https://www.loverslab.com/files/file/48837-example/"


def test_search_plan_from_query_plan_carries_metric_thresholds():
    plan = SearchPlan.from_query_plan(
        {
            "min_downloads": "1,000",
            "min_endorsements": 50,
            "min_views": "2,000",
            "min_likes": 25,
            "updated_since_days": 14,
            "updated_after": "2024-01-01T00:00:00+00:00",
            "published_before": "2024-12-31T23:59:59+00:00",
            "limit": 8,
        }
    )

    assert plan.min_downloads == 1000
    assert plan.min_endorsements == 50
    assert plan.min_views == 2000
    assert plan.min_likes == 25
    assert plan.updated_since_days == 14
    assert plan.to_query_plan()["min_downloads"] == 1000
    assert plan.to_query_plan()["min_endorsements"] == 50
    assert plan.to_query_plan()["min_views"] == 2000
    assert plan.to_query_plan()["min_likes"] == 25
    assert plan.to_query_plan()["updated_since_days"] == 14
    assert plan.updated_after == "2024-01-01T00:00:00+00:00"
    assert plan.published_before == "2024-12-31T23:59:59+00:00"
    assert plan.to_query_plan()["updated_after"] == "2024-01-01T00:00:00+00:00"
    assert plan.to_query_plan()["published_before"] == "2024-12-31T23:59:59+00:00"


def test_search_plan_from_query_plan_tolerates_invalid_numeric_fields():
    plan = SearchPlan.from_query_plan(
        {
            "limit": "many",
            "candidate_pool_limit": "200",
            "min_downloads": "bad",
            "updated_since_days": "400",
        }
    )

    assert plan.limit == 8
    assert plan.candidate_pool_limit == 80
    assert plan.min_downloads is None
    assert plan.updated_since_days == 365


def test_search_plan_from_query_plan_treats_string_false_open_discovery_as_false():
    plan = SearchPlan.from_query_plan({"open_discovery": "false", "retrieval_mode": "fuzzy"})

    assert plan.open_discovery is False
    assert "open_discovery" not in plan.to_query_plan()


def test_search_result_keeps_tool_source_and_score():
    mod = Mod(source="nexusmods", external_id="1", game="Stellar Blade", title="XXTB", url="https://example.com")
    result = SearchResult(score=5, mod=mod, tool_name="local_db_search")

    assert result.score == 5
    assert result.mod.title == "XXTB"
    assert result.tool_name == "local_db_search"
    assert result.retrieval_branch == ""

import ast
import importlib
import importlib.util
import inspect

from app.services.agent import query_planner


def test_query_plan_contract_centralizes_shared_field_groups():
    module_name = "app.services.agent.planning.query_plan_contract"
    assert importlib.util.find_spec(module_name) is not None
    contract = importlib.import_module(module_name)
    metric_fields = contract.METRIC_FIELDS
    date_range_fields = contract.DATE_RANGE_FIELDS
    current_only_fields = contract.CURRENT_ONLY_QUERY_PLAN_FIELDS

    assert metric_fields == (
        "min_downloads",
        "min_endorsements",
        "min_views",
        "min_likes",
    )
    assert date_range_fields == (
        "updated_after",
        "updated_before",
        "published_after",
        "published_before",
        "created_after",
        "created_before",
    )
    assert {
        *metric_fields,
        *date_range_fields,
        "keywords",
        "sources",
        "requirement_terms",
        "compatibility_terms",
        "evidence_id",
    } <= current_only_fields


def test_normalize_query_plan_is_a_small_orchestrator():
    source = inspect.getsource(query_planner.normalize_query_plan)
    tree = ast.parse(source)
    decisions = sum(
        isinstance(
            node,
            (
                ast.If,
                ast.IfExp,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.Try,
                ast.Match,
                ast.BoolOp,
            ),
        )
        for node in ast.walk(tree)
    )

    assert len(source.splitlines()) <= 70
    assert decisions <= 8

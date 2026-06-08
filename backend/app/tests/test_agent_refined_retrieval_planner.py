from app.services.agent.planning.refined_retrieval_planner import (
    RefinedRetrievalInput,
    build_refined_retrieval_plan,
)


def test_refined_retrieval_plan_preserves_hard_constraints_and_adds_direct_terms():
    plan = build_refined_retrieval_plan(
        RefinedRetrievalInput(
            original_query="只看天际的R18女性服装",
            query_plan={"game": "skyrimspecialedition", "adult_content": True, "keywords": ["female"]},
            semantic_strategy={
                "hard_filters": {"source": "nexusmods"},
                "direct_match_definition": ["female outfit", "clothing", "dress"],
                "support_context_definition": ["body preset"],
            },
            correction_plan={"keywords": ["armor", "bikini"]},
            detected_errors=["direct_match不足"],
        )
    )

    assert plan.query_plan["game"] == "skyrimspecialedition"
    assert plan.query_plan["games"] == ["skyrimspecialedition"]
    assert plan.query_plan["sources"] == ["nexusmods"]
    assert plan.query_plan["adult_content"] is True
    assert plan.query_plan["keywords"] == ["female", "female outfit", "clothing", "dress", "armor", "bikini"]
    assert "games=['skyrimspecialedition']" in plan.preserved_constraints
    assert "sources=['nexusmods']" in plan.preserved_constraints
    assert "adult_content=True" in plan.preserved_constraints
    assert "female outfit" in plan.retrieval_queries[0]


def test_refined_retrieval_plan_ignores_support_definition_as_direct_term():
    plan = build_refined_retrieval_plan(
        RefinedRetrievalInput(
            original_query="只看玩法本体",
            query_plan={},
            semantic_strategy={
                "direct_match_definition": ["gameplay framework", "body preset"],
                "support_context_definition": ["body preset"],
            },
            correction_plan={},
        )
    )

    assert plan.query_plan["keywords"] == ["gameplay framework"]


def test_refined_retrieval_plan_reruns_hygiene():
    plan = build_refined_retrieval_plan(
        RefinedRetrievalInput(
            original_query="只看女性服装",
            query_plan={"exact_title": "女性服装", "categories": ["Clothing", "Bimbos of Skyrim - BimboLips"]},
            semantic_strategy={"direct_match_definition": ["female clothing"]},
            correction_plan={},
        )
    )

    assert "exact_title" not in plan.query_plan
    assert plan.query_plan["categories"] == ["Clothing"]
    assert "hygiene_removed:exact_title" in plan.removed_pollution
    assert "hygiene_removed:categories:Bimbos of Skyrim - BimboLips" in plan.removed_pollution

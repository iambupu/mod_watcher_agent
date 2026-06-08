from app.services.agent.self_correction.self_correction_evidence import SelfCorrectionEvidence
from app.services.agent.tools.query_plan_repair_tool import (
    QueryPlanRepairInput,
    QueryPlanRepairTool,
)


def _evidence() -> SelfCorrectionEvidence:
    return SelfCorrectionEvidence(
        original_query="只看 Nexus 的 Skyrim 女性服装",
        current_goal="只看女性服装",
        hard_constraints={"games": ["skyrimspecialedition"], "sources": ["nexusmods"]},
    )


def test_query_plan_repair_removes_polluted_non_hard_fields_and_reruns_hygiene():
    result = QueryPlanRepairTool().run(
        QueryPlanRepairInput(
            original_query="只看 Nexus 的 Skyrim 女性服装",
            query_plan={
                "games": ["skyrimspecialedition"],
                "sources": ["nexusmods"],
                "exact_title": "女性服装",
                "categories": ["Clothing", "Bimbos of Skyrim - BimboLips"],
                "keywords": ["female", "clothing"],
            },
            correction_plan={"remove_fields": ["exact_title"], "query_plan": {"keywords": ["female outfit"]}},
            evidence=_evidence(),
            allowed_fields={"keywords"},
        )
    )

    assert "exact_title" not in result.query_plan
    assert result.query_plan["categories"] == ["Clothing"]
    assert result.query_plan["keywords"] == ["female outfit"]
    assert result.changed_fields == ["categories", "exact_title", "keywords"]
    assert "removed_field:exact_title" in result.removed_pollution
    assert "hygiene_removed:categories:Bimbos of Skyrim - BimboLips" in result.removed_pollution
    assert result.preserved_constraints == ["games=['skyrimspecialedition']", "sources=['nexusmods']"]


def test_query_plan_repair_does_not_remove_or_change_hard_constraints():
    result = QueryPlanRepairTool().run(
        QueryPlanRepairInput(
            original_query="只看 Nexus 的 Skyrim 女性服装",
            query_plan={"games": ["skyrimspecialedition"], "sources": ["nexusmods"]},
            correction_plan={
                "remove_fields": ["source"],
                "query_plan": {"games": ["cyberpunk2077"], "sources": ["loverslab"], "keywords": ["outfit"]},
            },
            evidence=_evidence(),
            allowed_fields={"games", "sources", "keywords"},
        )
    )

    assert result.query_plan["games"] == ["skyrimspecialedition"]
    assert result.query_plan["sources"] == ["nexusmods"]
    assert result.query_plan["keywords"] == ["outfit"]
    assert result.changed_fields == ["keywords"]

import pytest

from app.services.agent.semantic_search import semantic_query
from app.services.agent.tools.semantic_signal_tool import SemanticSignalInput, SemanticSignalTool


@pytest.mark.parametrize(
    ("query", "expected_anchor", "expected_domain"),
    [
        ("有什么在玩法上可以扮演bimbo的MOD", "roleplay", "mechanics"),
        ("有什么妓女风格的服装MOD", "sexworker_style", "content_type"),
        ("有什么mod支持怀孕玩法", "pregnancy", "mechanics"),
        ("爱的实验室有什么体系mod", "loverslab", "source_scope"),
    ],
)
def test_semantic_signal_tool_extracts_business_example_signals(query, expected_anchor, expected_domain):
    output = SemanticSignalTool().run(SemanticSignalInput(query=query))

    assert expected_anchor in output.anchors
    assert expected_domain in output.domains


def test_semantic_signal_tool_logs_evidence_id(caplog):
    with caplog.at_level("INFO"):
        SemanticSignalTool().run(SemanticSignalInput(query="有什么mod支持怀孕玩法", evidence_id="ev_signal"))

    assert any(
        "agent.tool name=semantic_signal_extractor status=succeeded" in record.message
        and "evidence_id=ev_signal" in record.message
        for record in caplog.records
    )


def test_semantic_query_exposes_task_understanding_concepts_without_broad_bimbo_keywords():
    output = semantic_query("有什么在玩法上可以扮演bimbo的MOD")

    assert {"bimbo", "roleplay"}.issubset(set(output.matched_concepts))
    assert {"bimbo", "roleplay"}.issubset(set(output.anchors))
    assert "mechanics" in output.domains
    assert "bimboification" not in output.expanded_terms
    assert "body morph" not in output.expanded_terms


@pytest.mark.parametrize(
    ("query", "expected_anchor", "expected_domain"),
    [
        ("找能让角色走 bimbo 路线的系统 mod", "roleplay", "mechanics"),
        ("有什么生育系统玩法 mod", "pregnancy", "mechanics"),
        ("找风尘感的衣服 mod", "sexworker_style", "content_type"),
    ],
)
def test_semantic_query_infers_compositional_signals_for_nearby_phrasings(query, expected_anchor, expected_domain):
    output = semantic_query(query)

    assert expected_anchor in output.anchors
    assert expected_domain in output.domains

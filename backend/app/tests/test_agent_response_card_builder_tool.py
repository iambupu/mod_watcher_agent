import logging

from app.services.agent.schemas import AgentModMatch
from app.services.agent.tools.response_card_builder_tool import (
    ResponseCardBuilderInput,
    ResponseCardBuilderTool,
)


def test_response_card_builder_tool_builds_cards_and_logs_evidence_id(caplog):
    caplog.set_level(logging.INFO)
    match = AgentModMatch(
        id=1,
        title="Pregnancy Gameplay Overhaul",
        source="loverslab",
        game="Skyrim Special Edition",
        author="Author",
        version=None,
        url="https://example.com/pregnancy",
        updated_at_remote=None,
        score=12,
        rank_reason="命中工具：sqlite_fts。",
    )

    output = ResponseCardBuilderTool().run(
        ResponseCardBuilderInput(
            query="有什么mod支持怀孕玩法",
            query_plan={"sort_field": "relevance", "sort_order": "desc"},
            matches=[match],
            evidence_id="ev_cards",
        )
    )

    assert list(output.cards.keys())[:3] == ["analysis", "evidence", "conclusion"]
    assert output.cards["analysis"][0] == "任务分析：有什么mod支持怀孕玩法"
    assert output.cards["evidence"][0] == "证据：检索返回 1 个候选。"
    assert output.cards["conclusion"][0] == "结论：优先查看前 1 个候选。"
    assert output.cards["understanding"] == ["我理解你想找：有什么mod支持怀孕玩法"]
    assert "Pregnancy Gameplay Overhaul" in output.cards["results"][1]
    assert any(
        "agent.tool name=response_card_builder status=succeeded matches=1" in item.message
        and "evidence_id=ev_cards" in item.message
        for item in caplog.records
    )

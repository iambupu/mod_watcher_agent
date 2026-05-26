from app.services.agent.response_builder import (
    build_detail_response_cards,
    build_response_cards,
    build_status_response_cards,
)
from app.services.agent.schemas import AgentModMatch


def test_build_response_cards_uses_generated_next_steps():
    match = AgentModMatch(
        id=1,
        title="MGO - Magic gameplay Overhaul SSE",
        source="nexusmods",
        game="Skyrim Special Edition",
        author="Bard",
        version=None,
        url="https://example.com/mgo",
        updated_at_remote=None,
        score=5,
    )
    generated_steps = ["要不要展开 MGO 的施法机制改动？", "只看 Skyrim 最近更新的魔法玩法 Mod？"]

    cards = build_response_cards(
        query="最近更新了哪些玩法类的 Mod",
        query_plan={"sort_field": "updated_at_remote", "sort_order": "desc"},
        matches=[match],
        next_steps=generated_steps,
    )

    assert cards["next_steps"] == generated_steps
    assert list(cards.keys())[:3] == ["analysis", "evidence", "conclusion"]


def test_build_response_cards_includes_rank_reason_when_available():
    match = AgentModMatch(
        id=1,
        title="Ocean String",
        source="nexusmods",
        game="Stellar Blade",
        author="Author",
        version=None,
        url="https://example.com/ocean",
        updated_at_remote=None,
        score=12,
        score_breakdown={"keyword_score": 10, "source_confidence": 2},
        rank_reason="命中工具：sqlite_fts, nexusmods_search；基础相关性 10。",
    )

    cards = build_response_cards(
        query="Stellar Blade 成人服装",
        query_plan={"sort_field": "relevance", "sort_order": "desc"},
        matches=[match],
    )

    assert "命中工具：sqlite_fts, nexusmods_search" in cards["results"][1]


def test_build_status_response_cards_uses_standard_order():
    cards = build_status_response_cards(
        analysis="任务分析：当前输入为空。",
        evidence="证据：消息为空。",
        conclusion="结论：需要补充查询。",
        understanding="请先输入查询。",
        result="当前没有结果。",
        next_step="例如：最近更新的 Stellar Blade 画面 Mod。",
    )

    assert list(cards.keys())[:3] == ["analysis", "evidence", "conclusion"]
    assert cards["understanding"] == ["请先输入查询。"]
    assert cards["next_steps"] == ["例如：最近更新的 Stellar Blade 画面 Mod。"]


def test_build_detail_response_cards_uses_standard_order():
    cards = build_detail_response_cards(
        title="Pregnancy Gameplay Overhaul",
        source="nexusmods",
        game="Skyrim Special Edition",
        generated=False,
    )

    assert list(cards.keys())[:3] == ["analysis", "evidence", "conclusion"]
    assert cards["analysis"][0] == "任务分析：详细解析 Pregnancy Gameplay Overhaul"
    assert "Pregnancy Gameplay Overhaul" in cards["evidence"][0]
    assert cards["filters"] == ["来源：nexusmods", "游戏：Skyrim Special Edition"]

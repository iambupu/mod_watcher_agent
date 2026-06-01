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
    assert cards["conclusion"] == ["结论：优先查看前 1 个候选。"]
    assert list(cards.keys())[:3] == ["analysis", "evidence", "conclusion"]


def test_build_response_cards_filters_truncated_json_next_steps():
    match = AgentModMatch(
        id=1,
        title="Bimbos Of Skyrim LE/SE",
        source="loverslab",
        game="Skyrim Special Edition",
        author="Author",
        version=None,
        url="https://example.com/bos",
        updated_at_remote=None,
        score=5,
    )

    cards = build_response_cards(
        query="天际有什么扮演bimbo的MOD",
        query_plan={"games": ["Skyrim Special Edition"]},
        matches=[match],
        next_steps=['["这个 MOD 有哪些安装风险？'],
    )

    assert all(not item.startswith("[") for item in cards["next_steps"])
    assert all(not item.startswith("[") for item in cards["conclusion"])
    assert cards["conclusion"] == ["结论：优先查看前 1 个候选。"]
    assert cards["next_steps"][0] == "请详细解析 Bimbos Of Skyrim LE/SE"


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


def test_build_response_cards_includes_mod_summary_in_results():
    match = AgentModMatch(
        id=1,
        title="Bimbos Of Skyrim LE/SE",
        source="loverslab",
        game="Skyrim Special Edition",
        author="Author",
        version=None,
        url="https://example.com/bos",
        updated_at_remote=None,
        score=100,
        original_summary="Adds bimbofied NPCs, quests, and a transformation curse for player and followers.",
        translated_summary="加入 bimbo 化 NPC、任务，以及可影响玩家或随从的转化诅咒。",
        rank_reason="命中工具：local_db_search；基础相关性 100。",
    )

    cards = build_response_cards(
        query="天际有什么扮演bimbo的MOD",
        query_plan={"games": ["Skyrim Special Edition"], "sort_field": "relevance"},
        matches=[match],
    )

    assert "说明：加入 bimbo 化 NPC" in cards["results"][1]
    assert "匹配：命中工具：local_db_search" in cards["results"][1]


def test_build_response_cards_includes_semantic_judge_groups():
    match = AgentModMatch(
        id=1,
        title="Bimbo Roleplay Framework",
        source="loverslab",
        game="Skyrim Special Edition",
        author="Author",
        version=None,
        url="https://example.com/roleplay",
        updated_at_remote=None,
        score=100,
        rank_reason="语义裁判：high / 核心玩法；direct roleplay mechanics",
    )

    cards = build_response_cards(
        query="天际有什么扮演bimbo的MOD",
        query_plan={
            "_agent_candidate_semantic_judge": {
                "status": "succeeded",
                "used_llm": True,
                "groups": [
                    {
                        "name": "core_gameplay",
                        "label": "核心玩法",
                        "candidate_ids": [1],
                        "reason": "main mechanics",
                    }
                ],
                "gaps": ["缺少安装风险证据"],
            }
        },
        matches=[match],
    )

    assert "候选裁判：LLM 语义裁判（succeeded）" in cards["evidence"]
    assert "语义分组：核心玩法（1 个）" in cards["evidence"]
    assert "证据缺口：缺少安装风险证据" in cards["evidence"]


def test_build_response_cards_no_match_next_step_uses_current_constraints():
    cards = build_response_cards(
        query="天际有什么扮演bimbo的MOD",
        query_plan={"games": ["Skyrim Special Edition"], "categories": ["Gameplay"]},
        matches=[],
    )

    assert "Skyrim Special Edition" in cards["next_steps"][0]
    assert "Gameplay" in cards["next_steps"][0]
    assert "Stellar Blade" not in cards["next_steps"][0]


def test_build_response_cards_no_match_next_step_is_neutral_without_constraints():
    cards = build_response_cards(query="有什么扮演bimbo的MOD", query_plan={}, matches=[])

    assert cards["next_steps"] == ["换成全部来源，再用更宽的关键词查一次"]


def test_build_status_response_cards_uses_standard_order():
    cards = build_status_response_cards(
        analysis="任务分析：当前输入为空。",
        evidence="证据：消息为空。",
        conclusion="结论：需要补充查询。",
        understanding="请先输入查询。",
        result="当前没有结果。",
        next_step="最近更新的 Stellar Blade 画面 Mod",
    )

    assert list(cards.keys())[:3] == ["analysis", "evidence", "conclusion"]
    assert cards["conclusion"] == ["结论：需要补充查询。"]
    assert cards["understanding"] == ["请先输入查询。"]
    assert cards["next_steps"] == ["最近更新的 Stellar Blade 画面 Mod"]


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
    assert cards["conclusion"] == ["结论：可以继续查看 Pregnancy Gameplay Overhaul 的详情。"]
    assert cards["filters"] == ["来源：nexusmods", "游戏：Skyrim Special Edition"]
    assert cards["next_steps"] == ["这个 Mod 适合我当前的游戏版本吗？"]

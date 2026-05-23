from app.services.agent.response_builder import build_response_cards
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

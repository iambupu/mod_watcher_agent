from app.services.agent.reflection.response_enrichment import apply_query_understanding_to_response
from app.services.agent.schemas import AgentChatResponse, AgentModMatch


def _match(game: str = "Skyrim Special Edition") -> AgentModMatch:
    return AgentModMatch(
        id=1,
        title="Bimbo Roleplay Systems",
        source="loverslab",
        game=game,
        category="Gameplay",
        author=None,
        version=None,
        url="https://example.test/mod",
        updated_at_remote=None,
        score=10,
    )


def test_response_enrichment_applies_diagnosis_and_query_plan_slots():
    response = AgentChatResponse(answer="ok", used_llm=False, matches=[], response_cards=None)
    diagnosis = {
        "clarifying_question": "你想看哪个游戏？",
        "understanding": {"intent": "search", "slots": {"keywords": ["bimbo"]}, "evidence": []},
    }

    apply_query_understanding_to_response(
        response,
        diagnosis,
        {
            "games": ["Skyrim Special Edition"],
            "sources": ["loverslab"],
            "categories": ["Gameplay"],
            "adult_content": True,
        },
    )

    assert response.clarifying_question == "你想看哪个游戏？"
    slots = response.understanding["slots"]
    assert slots["keywords"] == ["bimbo"]
    assert slots["game"] == "Skyrim Special Edition"
    assert slots["source"] == "loverslab"
    assert slots["category"] == "Gameplay"
    assert slots["adult_content"] is True


def test_response_enrichment_preserves_existing_slots_and_uses_match_game_fallback():
    response = AgentChatResponse(
        answer="ok",
        used_llm=False,
        matches=[_match(game="Fallout 4")],
        response_cards=None,
    )
    diagnosis = {"understanding": {"intent": "search", "slots": {"source": "nexusmods"}, "evidence": []}}

    apply_query_understanding_to_response(
        response,
        diagnosis,
        {
            "sources": ["loverslab"],
            "categories": ["Quest"],
        },
    )

    slots = response.understanding["slots"]
    assert slots["source"] == "nexusmods"
    assert slots["category"] == "Quest"
    assert slots["game"] == "Fallout 4"

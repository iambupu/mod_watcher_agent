from app.services.agent.schemas import AgentChatResponse, AgentModMatch


def apply_query_understanding_to_response(
    response: AgentChatResponse,
    diagnosis: object,
    query_plan: object,
) -> None:
    if not isinstance(diagnosis, dict):
        diagnosis = {}
    if diagnosis.get("understanding"):
        response.understanding = diagnosis.get("understanding")
    if diagnosis.get("clarifying_question"):
        response.clarifying_question = str(diagnosis.get("clarifying_question"))
    if isinstance(response.understanding, dict):
        sync_understanding_slots_from_query_plan(
            response.understanding,
            query_plan if isinstance(query_plan, dict) else {},
            response.matches,
        )


def sync_understanding_slots_from_query_plan(
    understanding: dict[str, object],
    query_plan: dict[str, object],
    matches: list[AgentModMatch],
) -> None:
    slots = understanding.get("slots")
    if not isinstance(slots, dict):
        slots = {}
        understanding["slots"] = slots
    for plan_key, slot_key in [
        ("games", "game"),
        ("sources", "source"),
        ("categories", "category"),
    ]:
        if slots.get(slot_key):
            continue
        values = query_plan.get(plan_key)
        if isinstance(values, list):
            first = next((str(value).strip() for value in values if str(value).strip()), "")
            if first:
                slots[slot_key] = first
    if slots.get("adult_content") is None and query_plan.get("adult_content") is not None:
        slots["adult_content"] = query_plan.get("adult_content")
    if not matches:
        return
    first = matches[0]
    if not slots.get("game") and first.game:
        slots["game"] = first.game

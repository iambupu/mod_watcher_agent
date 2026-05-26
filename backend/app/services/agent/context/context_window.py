from app.services.agent.schemas import AgentHistoryItem


def clean_history(history: list[AgentHistoryItem]) -> list[AgentHistoryItem]:
    cleaned: list[AgentHistoryItem] = []
    for item in history:
        role = (item.role or "").strip().lower()
        text = (item.text or "").strip()
        if role in {"user", "assistant"} and text:
            cleaned.append(AgentHistoryItem(role=role, text=text))
    return cleaned


def split_context_window(
    history: list[AgentHistoryItem],
    *,
    recent_message_count: int,
) -> tuple[list[AgentHistoryItem], list[AgentHistoryItem]]:
    cleaned = clean_history(history)
    if recent_message_count <= 0:
        return cleaned, []
    return cleaned[:-recent_message_count], cleaned[-recent_message_count:]

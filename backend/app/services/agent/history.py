from app.services.agent.schemas import AgentHistoryItem


def compress_history(
    history: list[AgentHistoryItem],
    max_items: int = 12,
    max_chars: int = 2200,
) -> tuple[str, list[AgentHistoryItem]]:
    """处理当前模块的业务逻辑并返回结果。"""
    cleaned = []
    for item in history:
        role = (item.role or "").strip().lower()
        text = (item.text or "").strip()
        if role in {"user", "assistant"} and text:
            cleaned.append(AgentHistoryItem(role=role, text=text))
    if not cleaned:
        return "", []

    recent = cleaned[-max_items:]
    older = cleaned[:-max_items]
    if not older:
        total_recent = sum(len(x.text) for x in recent)
        if total_recent <= max_chars:
            return "", recent
        merged = []
        size = 0
        for item in reversed(recent):
            take = len(item.text)
            if size + take > max_chars and merged:
                break
            merged.append(item)
            size += take
        merged.reverse()
        return "", merged

    older_lines = []
    for item in older[-8:]:
        prefix = "用户" if item.role == "user" else "助手"
        older_lines.append(f"{prefix}: {item.text[:180]}")
    summary = "上下文摘要（较早对话）:\n" + "\n".join(older_lines)
    if len(summary) > max_chars:
        summary = summary[:max_chars] + "..."
    return summary, recent

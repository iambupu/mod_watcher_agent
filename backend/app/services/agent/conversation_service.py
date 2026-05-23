import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlmodel import Session, delete, select

from app.models.agent_message import AgentMessage
from app.services.agent.schemas import (
    AgentConversationMessage,
    AgentConversationState,
    AgentConversationStateSaveRequest,
    AgentModMatch,
)
from app.services.settings_service import SettingsService

AGENT_CHAT_ACTIVE_SESSION_KEY = "agent_chat_active_session_id"
AGENT_CHAT_LAST_UPDATE_PREFIX = "agent_chat_last_updated_at_"
MAX_CONVERSATION_MESSAGES = 300
MAX_CONVERSATION_CHARS = 120000


def new_session_id() -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    return f"sess_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


def parse_utc_timestamp(raw: str | None) -> datetime | None:
    """解析输入内容并返回结构化结果。"""
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_conversation_state(session: Session, settings: SettingsService) -> AgentConversationState:
    """加载配置或持久化数据。"""
    rows = session.exec(select(AgentMessage).order_by(AgentMessage.id.asc())).all()
    session_order: dict[str, int] = {}
    for row in rows:
        if row.session_id not in session_order:
            session_order[row.session_id] = row.id or 0
    rows.sort(key=lambda row: (session_order.get(row.session_id, row.id or 0), row.sort_index, row.id or 0))
    raw_active_session = settings.get(AGENT_CHAT_ACTIVE_SESSION_KEY) or ""
    parsed_messages: list[AgentConversationMessage] = []
    for row in rows:
        matches: list[AgentModMatch] | None = None
        response_cards: dict[str, list[str]] | None = None
        if row.matches_json:
            try:
                raw_matches = json.loads(row.matches_json)
                if isinstance(raw_matches, list):
                    matches = [AgentModMatch(**item) for item in raw_matches if isinstance(item, dict)]
            except Exception:
                matches = None
        if row.response_cards_json:
            try:
                raw_cards = json.loads(row.response_cards_json)
                if isinstance(raw_cards, dict):
                    response_cards = {
                        "understanding": [str(x) for x in (raw_cards.get("understanding") or []) if str(x).strip()],
                        "filters": [str(x) for x in (raw_cards.get("filters") or []) if str(x).strip()],
                        "results": [str(x) for x in (raw_cards.get("results") or []) if str(x).strip()],
                        "next_steps": [str(x) for x in (raw_cards.get("next_steps") or []) if str(x).strip()],
                    }
            except Exception:
                response_cards = None
        parsed_messages.append(
            AgentConversationMessage(
                id=row.message_id,
                role=row.role,
                text=row.text,
                session_id=row.session_id,
                created_at=row.created_at,
                matches=matches,
                response_cards=response_cards,
                llm_provider=row.llm_provider,
                llm_model=row.llm_model,
            )
        )

    active_session = raw_active_session.strip() or (
        parsed_messages[-1].session_id if parsed_messages else new_session_id()
    )
    return AgentConversationState(messages=parsed_messages, active_session_id=active_session)


def save_conversation_state(
    *,
    body: AgentConversationStateSaveRequest,
    session: Session,
    settings: SettingsService,
) -> AgentConversationState:
    """保存数据并返回最新状态。"""
    now = datetime.now(UTC).isoformat()
    active_session = body.active_session_id.strip() or new_session_id()
    last_update_key = f"{AGENT_CHAT_LAST_UPDATE_PREFIX}{active_session}"
    incoming_updated_at = parse_utc_timestamp(body.client_updated_at)
    if body.client_updated_at and incoming_updated_at is None:
        raise HTTPException(status_code=422, detail="client_updated_at must be ISO timestamp")
    persisted_updated_at = parse_utc_timestamp(settings.get(last_update_key))
    if incoming_updated_at and persisted_updated_at and incoming_updated_at < persisted_updated_at:
        raise HTTPException(
            status_code=409,
            detail="conversation state is stale; refresh conversation and retry",
        )
    normalized: list[dict] = []
    for message in body.messages[-MAX_CONVERSATION_MESSAGES:]:
        msg = AgentConversationMessage(
            id=str(message.id),
            role=message.role,
            text=str(message.text),
            session_id=str(message.session_id),
            created_at=message.created_at or now,
            matches=message.matches or None,
            response_cards=message.response_cards or None,
            llm_provider=message.llm_provider,
            llm_model=message.llm_model,
        )
        normalized.append(msg.model_dump())
    active_messages = [
        item
        for item in normalized
        if str(item.get("session_id") or "").strip() == active_session
    ]
    if active_messages:
        total_chars = sum(len(str(item.get("text") or "")) for item in active_messages)
        if total_chars > MAX_CONVERSATION_CHARS:
            trimmed: list[dict] = []
            running_chars = 0
            for item in reversed(active_messages):
                text_len = len(str(item.get("text") or ""))
                if running_chars + text_len > MAX_CONVERSATION_CHARS and trimmed:
                    break
                trimmed.append(item)
                running_chars += text_len
            trimmed.reverse()
            active_messages = trimmed
    existing_rows = session.exec(
        select(AgentMessage).where(AgentMessage.session_id == active_session)
    ).all()
    existing_by_message_id = {row.message_id: row for row in existing_rows}
    seen_message_ids: set[str] = set()
    rows_to_add: list[AgentMessage] = []
    for idx, item in enumerate(active_messages):
        message_id = str(item.get("id") or "")
        if not message_id:
            continue
        seen_message_ids.add(message_id)
        role = str(item.get("role") or "assistant")
        text_value = str(item.get("text") or "")
        session_id = str(item.get("session_id") or "")
        created_at = str(item.get("created_at") or now)
        matches_json = json.dumps(item.get("matches"), ensure_ascii=False) if item.get("matches") else None
        response_cards_json = json.dumps(item.get("response_cards"), ensure_ascii=False) if item.get("response_cards") else None
        llm_provider = str(item.get("llm_provider") or "") or None
        llm_model = str(item.get("llm_model") or "") or None
        existing = existing_by_message_id.get(message_id)
        if existing:
            existing.role = role
            existing.text = text_value
            existing.session_id = session_id
            existing.created_at = created_at
            existing.matches_json = matches_json
            existing.response_cards_json = response_cards_json
            existing.llm_provider = llm_provider
            existing.llm_model = llm_model
            existing.sort_index = idx
            session.add(existing)
            continue
        rows_to_add.append(
            AgentMessage(
                message_id=message_id,
                role=role,
                text=text_value,
                session_id=session_id,
                created_at=created_at,
                matches_json=matches_json,
                response_cards_json=response_cards_json,
                llm_provider=llm_provider,
                llm_model=llm_model,
                sort_index=idx,
            ),
        )
    if rows_to_add:
        session.add_all(rows_to_add)
    if seen_message_ids:
        session.exec(
            delete(AgentMessage).where(
                AgentMessage.session_id == active_session,
                AgentMessage.message_id.notin_(seen_message_ids),
            )
        )
    else:
        session.exec(delete(AgentMessage).where(AgentMessage.session_id == active_session))
    session.commit()
    settings.set(AGENT_CHAT_ACTIVE_SESSION_KEY, active_session)
    settings.set(last_update_key, now)
    return load_conversation_state(session, settings)


def start_new_conversation(settings: SettingsService) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    session_id = new_session_id()
    settings.set(AGENT_CHAT_ACTIVE_SESSION_KEY, session_id)
    return session_id

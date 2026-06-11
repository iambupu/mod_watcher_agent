import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlmodel import Session, delete, select

from app.models.agent_message import AgentMessage
from app.services.agent.memory.preference_service import AgentPreferenceService
from app.services.agent.schemas import (
    AgentAudit,
    AgentConversationMessage,
    AgentConversationState,
    AgentConversationStateSaveRequest,
    AgentModMatch,
)
from app.services.settings_service import SettingsService
from app.utils.json import json_array, json_object
from app.utils.time import parse_utc_datetime

AGENT_CHAT_ACTIVE_SESSION_KEY = "agent_chat_active_session_id"
AGENT_CHAT_LAST_UPDATE_PREFIX = "agent_chat_last_updated_at_"
MAX_CONVERSATION_MESSAGES = 300
MAX_CONVERSATION_CHARS = 120000


def new_session_id() -> str:
    """生成前端可追踪的会话 ID，时间戳便于人工排查保存顺序。"""
    return f"sess_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


def load_conversation_state(session: Session, settings: SettingsService) -> AgentConversationState:
    """按会话首次出现顺序加载全部消息，并恢复当前活动会话。"""
    rows = session.exec(select(AgentMessage).order_by(AgentMessage.id.asc())).all()
    session_order: dict[str, int] = {}
    for row in rows:
        if row.session_id not in session_order:
            session_order[row.session_id] = row.id or 0
    rows.sort(key=lambda row: (session_order.get(row.session_id, row.id or 0), row.sort_index, row.id or 0))
    raw_active_session = settings.get(AGENT_CHAT_ACTIVE_SESSION_KEY) or ""
    parsed_messages: list[AgentConversationMessage] = []
    for row in rows:
        # 持久化 JSON 可能来自旧版本或手工编辑，解析失败时丢弃扩展字段但保留消息正文。
        matches: list[AgentModMatch] | None = None
        response_cards: dict[str, list[str]] | None = None
        audit: AgentAudit | None = None
        if row.matches_json:
            parsed_matches = [
                match
                for item in json_array(row.matches_json)
                if isinstance(item, dict) and (match := _safe_agent_mod_match(item)) is not None
            ]
            matches = parsed_matches or None
        if row.response_cards_json:
            raw_cards = json_object(row.response_cards_json)
            response_cards = _normalize_response_cards(raw_cards) if raw_cards else None
        if row.audit_json:
            raw_audit = json_object(row.audit_json)
            try:
                audit = AgentAudit.model_validate(raw_audit) if raw_audit else None
            except Exception:
                audit = None
        parsed_messages.append(
            AgentConversationMessage(
                id=row.message_id,
                role=row.role,
                text=row.text,
                session_id=row.session_id,
                created_at=row.created_at,
                matches=matches,
                response_cards=response_cards,
                audit=audit,
                llm_provider=row.llm_provider,
                llm_model=row.llm_model,
            )
        )

    active_session = raw_active_session.strip() or (
        parsed_messages[-1].session_id if parsed_messages else new_session_id()
    )
    return AgentConversationState(messages=parsed_messages, active_session_id=active_session)


def _safe_agent_mod_match(item: dict) -> AgentModMatch | None:
    try:
        return AgentModMatch(**item)
    except Exception:
        return None


def save_conversation_state(
    *,
    body: AgentConversationStateSaveRequest,
    session: Session,
    settings: SettingsService,
) -> AgentConversationState:
    """保存单个活动会话的快照，并用 client_updated_at 拒绝过期写入。"""
    now = datetime.now(UTC).isoformat()
    active_session = body.active_session_id.strip() or new_session_id()
    last_update_key = f"{AGENT_CHAT_LAST_UPDATE_PREFIX}{active_session}"
    incoming_updated_at = parse_utc_datetime(body.client_updated_at)
    if body.client_updated_at and incoming_updated_at is None:
        raise HTTPException(status_code=422, detail="client_updated_at must be ISO timestamp")
    persisted_updated_at = parse_utc_datetime(settings.get(last_update_key))
    if incoming_updated_at and persisted_updated_at and incoming_updated_at < persisted_updated_at:
        # 前端可能有多个窗口；过期快照必须 409，让客户端 refetch 后再决定是否重试。
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
            audit=message.audit,
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
            # 长对话按字符预算从尾部保留，优先保证最近上下文仍能恢复。
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
        audit_json = json.dumps(item.get("audit"), ensure_ascii=False) if item.get("audit") else None
        llm_provider = str(item.get("llm_provider") or "") or None
        llm_model = str(item.get("llm_model") or "") or None
        existing = existing_by_message_id.get(message_id)
        if existing:
            # 以 message_id 做幂等更新，避免 debounce/retry 造成重复行。
            existing.role = role
            existing.text = text_value
            existing.session_id = session_id
            existing.created_at = created_at
            existing.matches_json = matches_json
            existing.response_cards_json = response_cards_json
            existing.audit_json = audit_json
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
                audit_json=audit_json,
                llm_provider=llm_provider,
                llm_model=llm_model,
                sort_index=idx,
            ),
        )
    try:
        if rows_to_add:
            session.add_all(rows_to_add)
        if seen_message_ids:
            # 快照保存语义是“当前活动会话的完整状态”，未出现的旧消息需要删除。
            session.exec(
                delete(AgentMessage).where(
                    AgentMessage.session_id == active_session,
                    AgentMessage.message_id.notin_(seen_message_ids),
                )
            )
        else:
            session.exec(delete(AgentMessage).where(AgentMessage.session_id == active_session))
        AgentPreferenceService(session).mark_dirty(commit=False)
        # 活动会话和更新时间与消息写入同事务提交，避免前端看到半更新状态。
        settings.set(AGENT_CHAT_ACTIVE_SESSION_KEY, active_session, commit=False)
        settings.set(last_update_key, now, commit=False)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return load_conversation_state(session, settings)


def _normalize_response_cards(raw_cards: dict) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for key, values in raw_cards.items():
        card_key = str(key or "").strip()
        if not card_key:
            continue
        if not isinstance(values, list):
            continue
        normalized_values = [str(item).strip() for item in values if str(item).strip()]
        if normalized_values:
            normalized[card_key] = normalized_values
    return normalized


def start_new_conversation(settings: SettingsService) -> str:
    """创建新会话并立即设为活动会话。"""
    session_id = new_session_id()
    settings.set(AGENT_CHAT_ACTIVE_SESSION_KEY, session_id)
    return session_id

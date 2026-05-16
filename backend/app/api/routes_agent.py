import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, delete, select

from app.db import get_session
from app.models.agent_message import AgentMessage
from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.llm_client import DEFAULT_MODELS, create_llm_client
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list["AgentHistoryItem"] = []


class AgentHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class AgentModDetailRequest(BaseModel):
    mod_id: int
    question: str | None = Field(default=None, max_length=4000)
    history: list[AgentHistoryItem] = []


class AgentModMatch(BaseModel):
    id: int
    title: str
    source: str
    game: str
    author: str | None
    version: str | None
    url: str
    updated_at_remote: str | None
    score: int
    original_summary: str | None = None
    translated_summary: str | None = None


class AgentChatResponse(BaseModel):
    answer: str
    used_llm: bool
    matches: list[AgentModMatch]


class AgentConversationMessage(BaseModel):
    id: str
    role: Literal["user", "assistant", "separator"]
    text: str
    session_id: str
    created_at: str | None = None
    matches: list[AgentModMatch] | None = None


class AgentConversationState(BaseModel):
    messages: list[AgentConversationMessage]
    active_session_id: str


class AgentConversationStateSaveRequest(BaseModel):
    messages: list[AgentConversationMessage]
    active_session_id: str


class AgentConversationNewResponse(BaseModel):
    session_id: str


AGENT_CHAT_ACTIVE_SESSION_KEY = "agent_chat_active_session_id"
MAX_CONVERSATION_MESSAGES = 300
MAX_CONVERSATION_CHARS = 120000
AGENT_RATE_LIMIT_CAPACITY = 12.0
AGENT_RATE_LIMIT_REFILL_PER_SEC = 0.2  # 12 tokens/min
AGENT_RATE_LIMIT_BURST = 20.0
AGENT_RATE_BUCKET_TTL_SEC = 300.0
_AGENT_RATE_BUCKETS: dict[str, tuple[float, float]] = {}
_AGENT_RATE_LOCK = threading.Lock()


def _new_session_id() -> str:
    return f"sess_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


def _build_rate_limit_key(request: Request, settings: SettingsService) -> str:
    active_session = (settings.get(AGENT_CHAT_ACTIVE_SESSION_KEY) or "").strip()
    if active_session:
        return f"agent:{active_session}"
    client_host = request.client.host if request.client else "unknown"
    return f"agent-ip:{client_host}"


def _enforce_rate_limit(key: str) -> None:
    now = time.monotonic()
    with _AGENT_RATE_LOCK:
        stale_keys = [k for k, (_, last_seen) in _AGENT_RATE_BUCKETS.items() if now - last_seen > AGENT_RATE_BUCKET_TTL_SEC]
        for stale_key in stale_keys:
            _AGENT_RATE_BUCKETS.pop(stale_key, None)
        tokens, last = _AGENT_RATE_BUCKETS.get(key, (AGENT_RATE_LIMIT_CAPACITY, now))
        elapsed = max(0.0, now - last)
        tokens = min(AGENT_RATE_LIMIT_BURST, tokens + elapsed * AGENT_RATE_LIMIT_REFILL_PER_SEC)
        if tokens < 1.0:
            wait_seconds = max(1, int((1.0 - tokens) / AGENT_RATE_LIMIT_REFILL_PER_SEC))
            raise HTTPException(status_code=429, detail=f"请求过于频繁，请在 {wait_seconds}s 后重试。")
        _AGENT_RATE_BUCKETS[key] = (tokens - 1.0, now)


def _load_conversation_state(session: Session, settings: SettingsService) -> AgentConversationState:
    rows = session.exec(select(AgentMessage).order_by(AgentMessage.sort_index.asc(), AgentMessage.id.asc())).all()
    raw_active_session = settings.get(AGENT_CHAT_ACTIVE_SESSION_KEY) or ""
    parsed_messages: list[AgentConversationMessage] = []
    for row in rows:
        matches: list[AgentModMatch] | None = None
        if row.matches_json:
            try:
                raw_matches = json.loads(row.matches_json)
                if isinstance(raw_matches, list):
                    matches = [AgentModMatch(**item) for item in raw_matches if isinstance(item, dict)]
            except Exception:
                matches = None
        parsed_messages.append(
            AgentConversationMessage(
                id=row.message_id,
                role=row.role,
                text=row.text,
                session_id=row.session_id,
                created_at=row.created_at,
                matches=matches,
            )
        )

    active_session = raw_active_session.strip() or (
        parsed_messages[-1].session_id if parsed_messages else _new_session_id()
    )
    return AgentConversationState(messages=parsed_messages, active_session_id=active_session)


def _compress_history(history: list[AgentHistoryItem], max_items: int = 12, max_chars: int = 2200) -> tuple[str, list[AgentHistoryItem]]:
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


def _score_mod(query: str, mod: Mod) -> int:
    q = query.lower().strip()
    tokens = [t for t in re.split(r"[^\w\u4e00-\u9fff]+", q) if t]
    if not tokens:
        return 0
    haystack = " ".join(
        [
            mod.title or "",
            mod.game or "",
            mod.author or "",
            mod.category or "",
            mod.original_summary or "",
        ]
    ).lower()
    score = sum(1 for token in tokens if token in haystack)
    if q and q in haystack:
        score += 2
    return score


def _is_recent_query(query: str) -> bool:
    q = query.lower()
    recent_words = [
        "最近",
        "最新",
        "更新",
        "recent",
        "latest",
        "new",
        "updated",
    ]
    mod_words = ["mod", "mods", "模组"]
    has_recent = any(word in q for word in recent_words)
    has_mod = any(word in q for word in mod_words)
    return has_recent and has_mod


def _safe_json_loads(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


async def _plan_query_with_llm(
    *,
    query: str,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    history: list[AgentHistoryItem],
) -> dict | None:
    client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
    history_summary, recent_history = _compress_history(history, max_items=8, max_chars=1200)
    prompt_lines = [
        "你是 Mod 数据库查询规划器。请根据用户意图输出 JSON 查询计划。",
        "数据库结构（表: mods）字段：",
        "- id(int), source(str), external_id(str), game(str), title(str), url(str)",
        "- author(str|null), category(str|null), tags_json(str JSON array)",
        "- original_summary(str|null), version(str|null), updated_at_remote(str|null)",
        "- first_seen_at(str), last_seen_at(str), ignored(bool)",
        "输出规则：",
        "1) 只输出一个 JSON 对象，不要额外解释",
        "2) JSON 结构:",
        '{ "intent":"recent|search|author|game|unknown", "keywords":[string], "game":"", "author":"", "source":"", "sort":"updated|first_seen|relevance", "limit":8 }',
        "3) 如果用户在问最近更新，intent=recent 且 sort=updated",
        "4) limit 范围 1~20，默认 8",
        "5) 当用户需求不明确时，intent=search，并提取 3~8 个关键词到 keywords",
    ]
    if history_summary:
        prompt_lines.extend(["", history_summary])
    if recent_history:
        prompt_lines.append("最近对话：")
        for item in recent_history:
            prefix = "用户" if item.role == "user" else "助手"
            prompt_lines.append(f"{prefix}: {item.text[:180]}")
    prompt_lines.extend(["", f"用户问题：{query}"])
    plan_text = await client.chat("\n".join(prompt_lines), model=model, max_tokens=240)
    plan = _safe_json_loads(plan_text)
    if not isinstance(plan, dict):
        return None
    return plan


def _apply_query_plan(
    mods: list[Mod],
    query: str,
    plan: dict | None,
    extra_text_by_mod: dict[int, str] | None = None,
) -> list[tuple[int, Mod]]:
    if not mods:
        return []
    if not isinstance(plan, dict):
        scored = []
        for mod in mods:
            if mod.id is None:
                continue
            score = _score_mod(query, mod)
            if score > 0:
                scored.append((score, mod))
        scored.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
        return scored[:8]

    intent = str(plan.get("intent") or "").strip().lower()
    keywords = [str(x).strip().lower() for x in (plan.get("keywords") or []) if str(x).strip()]
    game = str(plan.get("game") or "").strip().lower()
    author = str(plan.get("author") or "").strip().lower()
    source = str(plan.get("source") or "").strip().lower()
    sort = str(plan.get("sort") or "").strip().lower() or "relevance"
    try:
        limit = int(plan.get("limit") or 8)
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(20, limit))

    filtered = []
    for mod in mods:
        if mod.id is None:
            continue
        if game and game not in (mod.game or "").lower():
            continue
        if author and author not in (mod.author or "").lower():
            continue
        if source and source not in (mod.source or "").lower():
            continue
        haystack = " ".join(
            [mod.title or "", mod.game or "", mod.author or "", mod.category or "", mod.original_summary or ""]
        ).lower()
        extra_text = (extra_text_by_mod or {}).get(mod.id or 0, "").lower()
        full_haystack = f"{haystack} {extra_text}".strip()
        if keywords and not any(k in full_haystack for k in keywords):
            continue
        filtered.append(mod)

    if intent == "recent":
        filtered = sorted(filtered or mods, key=lambda m: (m.updated_at_remote or "", m.first_seen_at or ""), reverse=True)
        return [(1, m) for m in filtered[:limit] if m.id is not None]

    scored = []
    for mod in (filtered or mods):
        score = _score_mod(query, mod)
        if keywords:
            haystack = " ".join(
                [mod.title or "", mod.game or "", mod.author or "", mod.category or "", mod.original_summary or ""]
            ).lower()
            extra_text = (extra_text_by_mod or {}).get(mod.id or 0, "").lower()
            full_haystack = f"{haystack} {extra_text}".strip()
            score += sum(1 for k in keywords if k and k in full_haystack)
        if score <= 0 and keywords:
            score = 1
        if score > 0:
            scored.append((score, mod))
    if sort == "updated":
        scored.sort(key=lambda item: ((item[1].updated_at_remote or ""), item[0]), reverse=True)
    elif sort == "first_seen":
        scored.sort(key=lambda item: (item[1].first_seen_at, item[0]), reverse=True)
    else:
        scored.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
    return scored[:limit]


def _get_llm_config(settings: SettingsService) -> tuple[str, str, str, str]:
    providers_raw = settings.get("llm_providers_json") or "[]"
    try:
        providers = json.loads(providers_raw)
    except json.JSONDecodeError:
        providers = []

    enabled = []
    for item in providers:
        if isinstance(item, dict) and item.get("enabled"):
            enabled.append(item)
    enabled.sort(key=lambda item: int(item.get("priority") or 999))

    if enabled:
        p = enabled[0]
        provider = str(p.get("provider") or "openai").strip().lower()
        api_key = str(p.get("api_key") or "")
        base_url = str(p.get("base_url") or "")
        model = str(p.get("model") or "") or DEFAULT_MODELS.get(provider, "gpt-4o-mini")
        return provider, api_key, base_url, model

    provider = (settings.get("llm_provider") or "openai").strip().lower()
    api_key = settings.get("llm_api_key") or settings.get("openai_api_key") or ""
    base_url = settings.get("llm_base_url") or ""
    model = (settings.get("llm_model") or "").strip() or DEFAULT_MODELS.get(provider, "gpt-4o-mini")
    return provider, api_key, base_url, model


def _build_summary_map(session: Session, mod_ids: list[int]) -> dict[int, str]:
    language = SettingsService(session).get("summary_language") or "zh-CN"
    if not mod_ids:
        return {}

    summary_by_mod: dict[int, str] = {}
    summary_rows = session.exec(
        select(ModSummary.mod_id, ModSummary.content)
        .where(
            ModSummary.mod_id.in_(mod_ids),
            ModSummary.language == language,
            ModSummary.summary_type == "brief",
        )
        .order_by(ModSummary.id.desc())
    ).all()
    for mod_id, content in summary_rows:
        if mod_id not in summary_by_mod:
            summary_by_mod[mod_id] = content

    if language != "en":
        fallback_rows = session.exec(
            select(ModSummary.mod_id, ModSummary.content)
            .where(
                ModSummary.mod_id.in_(mod_ids),
                ModSummary.language == "en",
                ModSummary.summary_type == "brief",
            )
            .order_by(ModSummary.id.desc())
        ).all()
        for mod_id, content in fallback_rows:
            if mod_id not in summary_by_mod:
                summary_by_mod[mod_id] = content
    return summary_by_mod


def _build_search_text_map(session: Session, mod_ids: list[int]) -> dict[int, str]:
    if not mod_ids:
        return {}
    rows = session.exec(
        select(ModSummary.mod_id, ModSummary.content)
        .where(
            ModSummary.mod_id.in_(mod_ids),
            ModSummary.summary_type.in_(["brief", "introduction"]),
        )
        .order_by(ModSummary.id.desc())
    ).all()
    text_parts: dict[int, list[str]] = {}
    for mod_id, content in rows:
        if not content:
            continue
        text_parts.setdefault(mod_id, []).append(content)
    return {mod_id: " ".join(parts) for mod_id, parts in text_parts.items()}


@router.post("/chat", response_model=AgentChatResponse)
async def chat_with_agent(
    body: AgentChatRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    query = body.message.strip()
    if not query:
        return AgentChatResponse(answer="请输入要查询的内容。", used_llm=False, matches=[])

    stmt = (
        select(Mod)
        .where(Mod.ignored == False)
        .order_by(Mod.first_seen_at.desc())
        .limit(300)
    )
    mods = session.exec(stmt).all()

    matches: list[AgentModMatch] = []

    settings = SettingsService(session)
    _enforce_rate_limit(_build_rate_limit_key(request, settings))
    provider, api_key, base_url, model = _get_llm_config(settings)
    llm_available = provider == "ollama" or bool(api_key.strip())

    query_plan = None
    if llm_available:
        query_plan = await _plan_query_with_llm(
            query=query,
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            history=body.history,
        )

    search_text_by_mod = _build_search_text_map(session, [m.id for m in mods if m.id is not None])
    rescored = _apply_query_plan(mods, query, query_plan, search_text_by_mod)
    if not rescored and _is_recent_query(query):
        recent_mods = sorted(
            mods,
            key=lambda m: (m.updated_at_remote or "", m.first_seen_at or ""),
            reverse=True,
        )
        rescored = [(1, mod) for mod in recent_mods[:8] if mod.id is not None]
    if rescored:
        top = rescored[:8]
        mod_ids = [mod.id for _, mod in top if mod.id is not None]
        summary_by_mod = _build_summary_map(session, mod_ids)
        matches = [
            AgentModMatch(
                id=mod.id or 0,
                title=mod.title,
                source=mod.source,
                game=mod.game,
                author=mod.author,
                version=mod.version,
                url=mod.url,
                updated_at_remote=mod.updated_at_remote,
                score=score,
                original_summary=mod.original_summary,
                translated_summary=summary_by_mod.get(mod.id or 0),
            )
            for score, mod in top
        ]
    if not matches:
        return AgentChatResponse(
            answer="没有找到明确匹配。我可以先给你“最近更新”列表，或按游戏名/作者名筛选。比如：最近更新的 Skyrim Mod。",
            used_llm=False,
            matches=[],
        )
    fallback_answer = "找到以下相关 Mod：\n" + "\n".join([f"- {item.title} ({item.source})" for item in matches])
    if not llm_available:
        return AgentChatResponse(answer=fallback_answer, used_llm=False, matches=matches)

    history_summary, recent_history = _compress_history(body.history)

    prompt_lines = [
        "你是 Mod 查询助手。请基于给定候选结果回答用户问题。",
        "要求：",
        "1) 优先给出最相关的 3-5 条",
        "2) 回答使用中文",
        "3) 不要编造未提供的数据",
        "4) 若上下文有历史偏好，优先延续用户偏好",
    ]
    if history_summary:
        prompt_lines.extend(["", history_summary])
    if recent_history:
        prompt_lines.append("")
        prompt_lines.append("最近对话：")
        for item in recent_history:
            prefix = "用户" if item.role == "user" else "助手"
            prompt_lines.append(f"{prefix}: {item.text[:280]}")
    prompt_lines.extend([
        "",
        f"用户问题：{query}",
        "候选结果：",
    ])
    for idx, item in enumerate(matches, start=1):
        prompt_lines.append(
            f"{idx}. title={item.title}; source={item.source}; game={item.game}; "
            f"author={item.author or 'unknown'}; version={item.version or 'unknown'}; url={item.url}"
        )
    prompt = "\n".join(prompt_lines)

    client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
    content = await client.chat(prompt, model=model, max_tokens=500)
    if not content.strip():
        return AgentChatResponse(answer=fallback_answer, used_llm=False, matches=matches)
    return AgentChatResponse(answer=content.strip(), used_llm=True, matches=matches)


@router.post("/mod-detail", response_model=AgentChatResponse)
async def ask_mod_detail(
    body: AgentModDetailRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    mod = session.get(Mod, body.mod_id)
    if mod is None:
        return AgentChatResponse(answer="未找到该 Mod。", used_llm=False, matches=[])

    summary_by_mod = _build_summary_map(session, [body.mod_id])
    match = AgentModMatch(
        id=mod.id or 0,
        title=mod.title,
        source=mod.source,
        game=mod.game,
        author=mod.author,
        version=mod.version,
        url=mod.url,
        updated_at_remote=mod.updated_at_remote,
        score=1,
        original_summary=mod.original_summary,
        translated_summary=summary_by_mod.get(mod.id or 0),
    )
    fallback = (
        f"Mod：{mod.title}\n"
        f"来源：{mod.source}\n"
        f"游戏：{mod.game}\n"
        f"作者：{mod.author or 'unknown'}\n"
        f"版本：{mod.version or 'unknown'}\n"
        f"链接：{mod.url}\n\n"
        f"译文摘要：{match.translated_summary or '暂无'}\n"
        f"原文摘要：{match.original_summary or '暂无'}"
    )

    settings = SettingsService(session)
    _enforce_rate_limit(_build_rate_limit_key(request, settings))
    provider, api_key, base_url, model = _get_llm_config(settings)
    llm_available = provider == "ollama" or bool(api_key.strip())
    if not llm_available:
        return AgentChatResponse(answer=fallback, used_llm=False, matches=[match])

    history_summary, recent_history = _compress_history(body.history)
    question = (body.question or "").strip() or "请详细介绍这个 Mod 的特点、适用人群、安装关注点和潜在风险。"
    prompt_lines = [
        "你是 Mod 查询助手，请只基于给定单个 Mod 信息，输出更详细解析。",
        "要求：",
        "1) 用中文回答",
        "2) 不编造未提供信息；不确定时明确说明",
        "3) 输出结构：核心特点 / 兼容性与风险 / 适合人群 / 建议下一步",
    ]
    if history_summary:
        prompt_lines.extend(["", history_summary])
    if recent_history:
        prompt_lines.append("")
        prompt_lines.append("最近对话：")
        for item in recent_history:
            prefix = "用户" if item.role == "user" else "助手"
            prompt_lines.append(f"{prefix}: {item.text[:280]}")

    prompt_lines.extend([
        "",
        f"用户问题：{question}",
        "Mod 信息：",
        f"title={mod.title}",
        f"source={mod.source}",
        f"game={mod.game}",
        f"author={mod.author or 'unknown'}",
        f"version={mod.version or 'unknown'}",
        f"url={mod.url}",
        f"translated_summary={match.translated_summary or ''}",
        f"original_summary={match.original_summary or ''}",
    ])
    prompt = "\n".join(prompt_lines)
    client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
    content = await client.chat(prompt, model=model, max_tokens=800)
    if not content.strip():
        return AgentChatResponse(answer=fallback, used_llm=False, matches=[match])
    return AgentChatResponse(answer=content.strip(), used_llm=True, matches=[match])


@router.get("/conversation-state", response_model=AgentConversationState)
async def get_conversation_state(
    session: Session = Depends(get_session),
):
    settings = SettingsService(session)
    return _load_conversation_state(session, settings)


@router.post("/conversation-state", response_model=AgentConversationState)
async def save_conversation_state(
    body: AgentConversationStateSaveRequest,
    session: Session = Depends(get_session),
):
    settings = SettingsService(session)
    now = datetime.now(timezone.utc).isoformat()
    normalized: list[dict] = []
    for message in body.messages[-MAX_CONVERSATION_MESSAGES:]:
        msg = AgentConversationMessage(
            id=str(message.id),
            role=message.role,
            text=str(message.text),
            session_id=str(message.session_id),
            created_at=message.created_at or now,
            matches=message.matches or None,
        )
        normalized.append(msg.model_dump())
    # Keep the newest messages within a bounded total text size to avoid
    # unbounded growth of the persisted conversation payload in agent_messages.
    if normalized:
        total_chars = sum(len(str(item.get("text") or "")) for item in normalized)
        if total_chars > MAX_CONVERSATION_CHARS:
            trimmed: list[dict] = []
            running_chars = 0
            for item in reversed(normalized):
                text_len = len(str(item.get("text") or ""))
                if running_chars + text_len > MAX_CONVERSATION_CHARS and trimmed:
                    break
                trimmed.append(item)
                running_chars += text_len
            trimmed.reverse()
            normalized = trimmed
    existing_rows = session.exec(select(AgentMessage)).all()
    existing_by_message_id = {row.message_id: row for row in existing_rows}
    seen_message_ids: set[str] = set()
    rows_to_add: list[AgentMessage] = []
    for idx, item in enumerate(normalized):
        message_id = str(item.get("id") or "")
        if not message_id:
            continue
        seen_message_ids.add(message_id)
        role = str(item.get("role") or "assistant")
        text_value = str(item.get("text") or "")
        session_id = str(item.get("session_id") or "")
        created_at = str(item.get("created_at") or now)
        matches_json = json.dumps(item.get("matches"), ensure_ascii=False) if item.get("matches") else None
        existing = existing_by_message_id.get(message_id)
        if existing:
            existing.role = role
            existing.text = text_value
            existing.session_id = session_id
            existing.created_at = created_at
            existing.matches_json = matches_json
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
                sort_index=idx,
            ),
        )
    if rows_to_add:
        session.add_all(rows_to_add)
    if seen_message_ids:
        session.exec(delete(AgentMessage).where(AgentMessage.message_id.notin_(seen_message_ids)))
    else:
        session.exec(delete(AgentMessage))
    session.commit()
    settings.set(AGENT_CHAT_ACTIVE_SESSION_KEY, body.active_session_id.strip() or _new_session_id())
    return _load_conversation_state(session, settings)


@router.post("/conversation/new", response_model=AgentConversationNewResponse)
async def start_new_conversation(
    session: Session = Depends(get_session),
):
    settings = SettingsService(session)
    session_id = _new_session_id()
    settings.set(AGENT_CHAT_ACTIVE_SESSION_KEY, session_id)
    return AgentConversationNewResponse(session_id=session_id)

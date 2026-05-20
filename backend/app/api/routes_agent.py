import asyncio
import json
import re
import time
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy import or_
from sqlmodel import Session, delete, select

from app.db import get_session
from app.models.agent_message import AgentMessage
from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.game_alias_service import (
    add_game_alias_mappings,
    alias_key,
    build_resolved_aliases,
)
from app.services.llm_client import DEFAULT_MODELS, create_llm_client
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/agent", tags=["agent"])
SessionDep = Annotated[Session, Depends(get_session)]


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list["AgentHistoryItem"] = []
    provider_override: str | None = Field(default=None, max_length=64)
    model_override: str | None = Field(default=None, max_length=128)


class AgentHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class AgentModDetailRequest(BaseModel):
    mod_id: int
    question: str | None = Field(default=None, max_length=4000)
    history: list[AgentHistoryItem] = []
    provider_override: str | None = Field(default=None, max_length=64)
    model_override: str | None = Field(default=None, max_length=128)


class AgentModMatch(BaseModel):
    id: int
    title: str
    source: str
    game: str
    game_domain: str | None = None
    category: str | None = None
    author: str | None
    version: str | None
    url: str
    updated_at_remote: str | None
    downloads: int | None = None
    endorsements: int | None = None
    likes: int | None = None
    adult_content: bool | None = None
    score: int
    original_summary: str | None = None
    translated_summary: str | None = None


class AgentChatResponse(BaseModel):
    answer: str
    used_llm: bool
    matches: list[AgentModMatch]
    response_cards: dict[str, list[str]] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


class AgentConversationMessage(BaseModel):
    id: str
    role: Literal["user", "assistant", "separator"]
    text: str
    session_id: str
    created_at: str | None = None
    matches: list[AgentModMatch] | None = None
    response_cards: dict[str, list[str]] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


class AgentConversationState(BaseModel):
    messages: list[AgentConversationMessage]
    active_session_id: str


class AgentConversationStateSaveRequest(BaseModel):
    messages: list[AgentConversationMessage]
    active_session_id: str
    client_updated_at: str | None = None


class AgentConversationNewResponse(BaseModel):
    session_id: str


AGENT_CHAT_ACTIVE_SESSION_KEY = "agent_chat_active_session_id"
AGENT_CHAT_LAST_UPDATE_PREFIX = "agent_chat_last_updated_at_"
MAX_CONVERSATION_MESSAGES = 300
MAX_CONVERSATION_CHARS = 120000
AGENT_RATE_LIMIT_CAPACITY = 12.0
AGENT_RATE_LIMIT_REFILL_PER_SEC = 0.2  # 12 tokens/min
AGENT_RATE_LIMIT_BURST = 20.0
AGENT_RATE_BUCKET_TTL_SEC = 300.0
_AGENT_RATE_BUCKETS: dict[str, tuple[float, float]] = {}
_AGENT_RATE_LOCK = asyncio.Lock()
SLOT_OPTION_LIMIT = 200
DEFAULT_AGENT_LIMIT = 8
MAX_AGENT_LIMIT = 20
RELEVANCE_PREFETCH_LIMIT = 50

FIELD_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "mods": {
        "id": "本地 Mod 主键",
        "source": "来源平台，例如 nexusmods 或 loverslab",
        "external_id": "源站资源 ID",
        "game": "游戏展示名称",
        "game_domain": "游戏标准域名或来源侧标识",
        "title": "Mod 标题",
        "url": "源站详情页 URL",
        "author": "作者名称",
        "category": "来源侧分类",
        "tags_json": "标签 JSON 数组字符串",
        "original_summary": "源站原文摘要",
        "version": "版本号",
        "created_at_remote": "源站创建时间",
        "updated_at_remote": "源站更新时间",
        "published_at_remote": "源站发布时间",
        "downloads": "下载量",
        "unique_downloads": "唯一下载量",
        "endorsements": "Nexus 背书/点赞数",
        "views": "浏览量",
        "likes": "喜欢数",
        "adult_content": "是否成人内容",
        "thumbnail_url": "缩略图 URL",
        "raw_json": "源站原始数据 JSON",
        "ignored": "用户是否忽略该 Mod",
        "first_seen_at": "首次被本系统发现时间",
        "last_seen_at": "最近一次被本系统看到时间",
    },
    "mod_summaries": {
        "mod_id": "关联 mods.id",
        "language": "摘要语言",
        "summary_type": "摘要类型，例如 brief 或 introduction",
        "content": "摘要正文",
        "model": "生成摘要使用的模型",
        "generated_at": "摘要生成时间",
    },
}

SORT_COLUMNS = {
    "updated_at_remote": Mod.updated_at_remote,
    "first_seen_at": Mod.first_seen_at,
    "created_at_remote": Mod.created_at_remote,
    "published_at_remote": Mod.published_at_remote,
    "downloads": Mod.downloads,
    "unique_downloads": Mod.unique_downloads,
    "endorsements": Mod.endorsements,
    "views": Mod.views,
    "likes": Mod.likes,
}


def _new_session_id() -> str:
    return f"sess_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


def _parse_utc_timestamp(raw: str | None) -> datetime | None:
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


def _build_rate_limit_key(request: Request, settings: SettingsService) -> str:
    active_session = (settings.get(AGENT_CHAT_ACTIVE_SESSION_KEY) or "").strip()
    if active_session:
        return f"agent:{active_session}"
    client_host = request.client.host if request.client else "unknown"
    return f"agent-ip:{client_host}"


async def _enforce_rate_limit(key: str) -> None:
    now = time.monotonic()
    async with _AGENT_RATE_LOCK:
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


def _detect_adult_constraint(query: str) -> bool | None:
    q = (query or "").lower()
    if not q:
        return None
    negative_markers = [
        "非成人",
        "不是成人",
        "不含成人",
        "排除成人",
        "exclude adult",
        "non adult",
        "non-adult",
        "sfw",
    ]
    positive_markers = [
        "成人",
        "r18",
        "nsfw",
        "adult",
        "18+",
    ]
    if any(marker in q for marker in negative_markers):
        return False
    if any(marker in q for marker in positive_markers):
        return True
    return None


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


def _field_description(table: str, column: str) -> str:
    return FIELD_DESCRIPTIONS.get(table, {}).get(column, "当前仅作为数据库字段参与查询/展示")


def _build_database_schema_text(session: Session) -> str:
    inspector = sqlalchemy_inspect(session.get_bind())
    lines = []
    for table_name in sorted(inspector.get_table_names()):
        lines.append(f"表 {table_name}:")
        for column in inspector.get_columns(table_name):
            name = str(column["name"])
            col_type = str(column["type"])
            lines.append(f"- {name} ({col_type}): {_field_description(table_name, name)}")
    return "\n".join(lines)


def _distinct_non_empty_values(session: Session, column: Any, limit: int = SLOT_OPTION_LIMIT) -> list[str]:
    rows = session.exec(
        select(column)
        .where(column.is_not(None), column != "")
        .distinct()
        .order_by(column)
        .limit(limit)
    ).all()
    return [str(value).strip() for value in rows if str(value or "").strip()]


def _load_slot_options(session: Session) -> dict[str, list[str]]:
    return {
        "games": _distinct_non_empty_values(session, Mod.game),
        "game_domains": _distinct_non_empty_values(session, Mod.game_domain),
        "categories": _distinct_non_empty_values(session, Mod.category),
        "sources": _distinct_non_empty_values(session, Mod.source),
    }


def _format_slot_options(options: dict[str, list[str]]) -> str:
    lines = []
    for key in ["games", "game_domains", "categories", "sources"]:
        values = options.get(key, [])
        lines.append(f"{key}: {json.dumps(values, ensure_ascii=False)}")
    return "\n".join(lines)


def _merge_unique(values: list[str], additions: list[str]) -> list[str]:
    merged = list(values)
    seen = set(values)
    for item in additions:
        if item not in seen:
            merged.append(item)
            seen.add(item)
    return merged


def _infer_allowed_values_from_text(text: str, aliases: dict[str, list[str]]) -> list[str]:
    key = alias_key(text)
    if not key:
        return []
    inferred: list[str] = []
    for alias_key_value, values in aliases.items():
        if alias_key_value and alias_key_value in key:
            inferred = _merge_unique(inferred, values)
    return inferred


def _normalize_allowed_list(
    raw: Any,
    allowed_values: list[str],
    aliases: dict[str, list[str]] | None = None,
) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    aliases = aliases or {}
    allowed_by_key = {alias_key(value): value for value in allowed_values}
    normalized = []
    seen = set()
    for item in raw:
        key = alias_key(str(item or ""))
        value = allowed_by_key.get(key)
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
            continue
        for aliased_value in aliases.get(key, []):
            if aliased_value not in seen:
                normalized.append(aliased_value)
                seen.add(aliased_value)
    return normalized


def _normalize_sort_field(raw: Any, intent: str) -> str:
    value = str(raw or "").strip().lower()
    aliases = {
        "updated": "updated_at_remote",
        "latest": "updated_at_remote",
        "recent": "updated_at_remote",
        "new": "first_seen_at",
        "first_seen": "first_seen_at",
        "created": "created_at_remote",
        "published": "published_at_remote",
        "download": "downloads",
        "downloads": "downloads",
        "unique_download": "unique_downloads",
        "endorsement": "endorsements",
        "endorsements": "endorsements",
        "like": "likes",
        "likes": "likes",
        "view": "views",
        "views": "views",
        "relevance": "relevance",
    }
    mapped = aliases.get(value, value)
    if mapped in SORT_COLUMNS or mapped == "relevance":
        return mapped
    return "updated_at_remote" if intent == "recent" else "relevance"


def _normalize_query_plan(plan: dict | None, query: str, slot_options: dict[str, list[str]]) -> dict[str, Any]:
    raw = plan if isinstance(plan, dict) else {}
    intent = str(raw.get("intent") or "search").strip().lower()
    if intent not in {"recent", "search", "author", "game", "unknown"}:
        intent = "search"

    game_aliases_raw = raw.get("game_aliases")
    if game_aliases_raw:
        add_game_alias_mappings(game_aliases_raw, slot_options["games"])
    game_aliases = build_resolved_aliases(slot_options["games"])
    keywords = [str(item).strip().lower() for item in raw.get("keywords") or [] if str(item).strip()]
    inferred_games = _infer_allowed_values_from_text(query, game_aliases)
    for keyword in keywords:
        inferred_games = _merge_unique(inferred_games, _infer_allowed_values_from_text(keyword, game_aliases))
    if inferred_games:
        alias_keys = set(game_aliases)
        keywords = [
            keyword
            for keyword in keywords
            if not any(key in alias_key(keyword) for key in alias_keys)
        ]
    adult_raw = raw.get("adult_content")
    if isinstance(adult_raw, bool):
        adult_content = adult_raw
    elif isinstance(adult_raw, str) and adult_raw.strip().lower() in {"true", "false"}:
        adult_content = adult_raw.strip().lower() == "true"
    else:
        adult_content = _detect_adult_constraint(query)

    try:
        limit = int(raw.get("limit") or DEFAULT_AGENT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_AGENT_LIMIT

    games = _normalize_allowed_list(raw.get("games") or raw.get("game"), slot_options["games"], game_aliases)

    return {
        "intent": intent,
        "keywords": keywords[:10],
        "games": _merge_unique(games, inferred_games),
        "game_domains": _normalize_allowed_list(raw.get("game_domains") or raw.get("game_domain"), slot_options["game_domains"]),
        "categories": _normalize_allowed_list(raw.get("categories") or raw.get("category"), slot_options["categories"]),
        "sources": _normalize_allowed_list(raw.get("sources") or raw.get("source"), slot_options["sources"]),
        "adult_content": adult_content,
        "sort_field": _normalize_sort_field(raw.get("sort_field") or raw.get("sort"), intent),
        "sort_order": "asc" if str(raw.get("sort_order") or "").strip().lower() == "asc" else "desc",
        "limit": max(1, min(MAX_AGENT_LIMIT, limit)),
    }


def _build_mod_query_from_plan(plan: dict[str, Any]):
    conditions = [Mod.ignored == False]  # noqa: E712
    game_values = plan.get("games") or []
    game_domain_values = plan.get("game_domains") or []
    if game_values or game_domain_values:
        game_conditions = []
        if game_values:
            game_conditions.append(Mod.game.in_(game_values))
        if game_domain_values:
            game_conditions.append(Mod.game_domain.in_(game_domain_values))
        conditions.append(or_(*game_conditions))

    categories = plan.get("categories") or []
    if categories:
        conditions.append(Mod.category.in_(categories))

    adult_content = plan.get("adult_content")
    if isinstance(adult_content, bool):
        conditions.append(Mod.adult_content == adult_content)

    sources = plan.get("sources") or []
    if sources:
        conditions.append(Mod.source.in_(sources))

    keyword_conditions = []
    for keyword in plan.get("keywords") or []:
        pattern = f"%{keyword}%"
        keyword_conditions.append(
            or_(
                Mod.title.ilike(pattern),
                Mod.author.ilike(pattern),
                Mod.category.ilike(pattern),
                Mod.original_summary.ilike(pattern),
            )
        )
    if keyword_conditions:
        conditions.append(or_(*keyword_conditions))

    sort_field = plan.get("sort_field") or "relevance"
    sort_column = SORT_COLUMNS.get(sort_field, Mod.first_seen_at)
    sort_expr = sort_column.asc() if plan.get("sort_order") == "asc" else sort_column.desc()
    query_limit = RELEVANCE_PREFETCH_LIMIT if sort_field == "relevance" else int(plan["limit"])
    return select(Mod).where(*conditions).order_by(sort_expr, Mod.first_seen_at.desc()).limit(query_limit)


def _validate_agent_sql(statement: Any, session: Session) -> str:
    compiled = statement.compile(bind=session.get_bind(), compile_kwargs={"literal_binds": False})
    sql = str(compiled).strip()
    # Strip SQL comments and normalise whitespace for validation
    normalized = re.sub(r"--.*?\n|/\*.*?\*/", "", sql, flags=re.DOTALL)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    forbidden = [" insert ", " update ", " delete ", " drop ", " alter ", " pragma "]
    if not re.match(r"^select\b", normalized) or " from mods" not in normalized or any(token in normalized for token in forbidden):
        raise HTTPException(status_code=500, detail="Agent SQL validation failed")
    return sql


def _query_mods_with_plan(session: Session, query: str, plan: dict[str, Any]) -> list[tuple[int, Mod]]:
    statement = _build_mod_query_from_plan(plan)
    _validate_agent_sql(statement, session)
    mods = session.exec(statement).all()
    if plan.get("sort_field") == "relevance":
        scored = [(max(_score_mod(query, mod), 1), mod) for mod in mods if mod.id is not None]
        scored.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
        return scored[: int(plan["limit"])]
    return [(max(_score_mod(query, mod), 1), mod) for mod in mods if mod.id is not None][: int(plan["limit"])]


async def _validate_matches_with_llm(
    *,
    query: str,
    matches: list[AgentModMatch],
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    query_plan: dict[str, Any] | None = None,
) -> list[AgentModMatch]:
    if not matches:
        return matches
    client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
    lines = [
        "你是 Mod 语义相关性重排器，作用类似 cross-encoder。",
        "SQL 阶段已经完成 game/game_domain/category/source/adult_content/time/sort 等结构化硬过滤。",
        "你的任务只判断“用户问题”和“候选 Mod”在语义需求上是否相关，不要重复否决结构化硬约束。",
        "仅输出 JSON：{\"items\":[{\"id\":int,\"score\":0.0,\"reason\":\"简短原因\"}]}。",
        "规则：",
        "1) score 范围 0~1，表示语义相关性",
        "2) 关注标题、分类、摘要、作者、指标与用户真实需求的匹配度",
        "3) 用户只问排序或泛查询时，不要因为标题不含关键词而降到 0",
        "4) 明显不满足语义需求的条目给 0~0.39；弱相关 0.4~0.59；相关 0.6~0.79；强相关 0.8~1",
        "5) 如果都不相关，items 返回空数组",
        "",
        f"用户问题：{query}",
        f"结构化查询词槽：{json.dumps(query_plan or {}, ensure_ascii=False)}",
        "候选：",
    ]
    for idx, item in enumerate(matches, start=1):
        lines.append(
            f"{idx}. id={item.id}; title={item.title}; game={item.game}; game_domain={item.game_domain or 'unknown'}; "
            f"category={item.category or 'unknown'}; source={item.source}; adult_content={item.adult_content}; "
            f"downloads={item.downloads}; endorsements={item.endorsements}; likes={item.likes}; "
            f"author={item.author or 'unknown'}; updated_at_remote={item.updated_at_remote or 'unknown'}; "
            f"translated_summary={(item.translated_summary or '')[:400]}; original_summary={(item.original_summary or '')[:400]}"
        )
    raw = await client.chat("\n".join(lines), model=model, max_tokens=200)
    data = _safe_json_loads(raw)
    if not isinstance(data, dict):
        return matches
    scored_raw = data.get("items")
    if not isinstance(scored_raw, list):
        return matches
    score_by_id: dict[int, float] = {}
    for item in scored_raw:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if not isinstance(raw_id, int) and not (isinstance(raw_id, str) and raw_id.isdigit()):
            continue
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError):
            continue
        score_by_id[int(raw_id)] = max(0.0, min(1.0, score))
    if not score_by_id:
        return matches
    reranked = [item for item in matches if score_by_id.get(item.id, 0.0) >= 0.4]
    if not reranked:
        # Do not let semantic reranking erase all SQL-hard-filtered candidates.
        # Fallback to the original candidates when model scoring is too strict/noisy.
        return matches
    reranked.sort(key=lambda item: (score_by_id.get(item.id, 0.0), item.score), reverse=True)
    return reranked


async def _plan_query_with_llm(
    *,
    query: str,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    history: list[AgentHistoryItem],
    database_schema: str,
    slot_options: dict[str, list[str]],
) -> dict | None:
    client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
    history_summary, recent_history = _compress_history(history, max_items=8, max_chars=1200)
    prompt_lines = [
        "你是 Mod 数据库查询意图识别器。请根据用户问题输出结构化查询词槽 JSON。",
        "数据库表结构与字段含义：",
        database_schema,
        "",
        "数据库中可匹配的枚举值如下。game、game_domain、category、source 必须只从这些枚举值中选择；可以选择多个。",
        _format_slot_options(slot_options),
        "输出规则：",
        "1) 只输出一个 JSON 对象，不要额外解释",
        "2) JSON 结构:",
        '{ "intent":"recent|search|author|game|unknown", "keywords":[string], "games":[string], "game_domains":[string], "categories":[string], "adult_content":true|false|null, "sources":[string], "sort_field":"updated_at_remote|first_seen_at|created_at_remote|published_at_remote|downloads|unique_downloads|endorsements|views|likes|relevance", "sort_order":"asc|desc", "limit":8, "game_aliases":[{"alias":string,"game":string}] }',
        "3) 用户说成人/R18/NSFW 时 adult_content=true；非成人/SFW/排除成人时 adult_content=false；未提及时为 null",
        "4) 下载量最高用 downloads desc；点赞/背书最高用 endorsements desc 或 likes desc；最近/最新/更新用 updated_at_remote desc",
        "5) limit 范围 1~20，默认 8",
        "6) keywords 只放无法映射到上述词槽的自由文本关键词",
        "7) 如果用户使用了翻译名/俗称/缩写，并且你能确定它对应某个 games 枚举值，请在 game_aliases 中输出映射，例如 {\"alias\":\"剑星\",\"game\":\"Stellar Blade\"}",
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
    adult_constraint = _detect_adult_constraint(query)
    if not isinstance(plan, dict):
        scored = []
        for mod in mods:
            if mod.id is None:
                continue
            if adult_constraint is not None and bool(mod.adult_content) != adult_constraint:
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
    has_explicit_constraints = bool(game or author or source or keywords or adult_constraint is not None)
    filtered = []
    for mod in mods:
        if mod.id is None:
            continue
        if adult_constraint is not None and bool(mod.adult_content) != adult_constraint:
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
        candidate_mods = filtered if filtered else ([] if has_explicit_constraints else mods)
        candidate_mods = sorted(
            candidate_mods,
            key=lambda m: (m.updated_at_remote or "", m.first_seen_at or ""),
            reverse=True,
        )
        if adult_constraint is not None:
            candidate_mods = [m for m in candidate_mods if bool(m.adult_content) == adult_constraint]
        return [(1, m) for m in candidate_mods[:limit] if m.id is not None]

    scored = []
    candidate_mods = filtered if filtered else ([] if has_explicit_constraints else mods)
    for mod in candidate_mods:
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


def _get_llm_config(
    settings: SettingsService,
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> tuple[str, str, str, str]:
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

    override_provider = (provider_override or "").strip().lower()
    override_model = (model_override or "").strip()

    if override_provider:
        for item in enabled:
            provider = str(item.get("provider") or "").strip().lower()
            if provider != override_provider:
                continue
            api_key = str(item.get("api_key") or "")
            base_url = str(item.get("base_url") or "")
            model = override_model or str(item.get("model") or "") or DEFAULT_MODELS.get(provider, "gpt-4o-mini")
            return provider, api_key, base_url, model

    if enabled:
        p = enabled[0]
        provider = str(p.get("provider") or "openai").strip().lower()
        api_key = str(p.get("api_key") or "")
        base_url = str(p.get("base_url") or "")
        model = override_model or str(p.get("model") or "") or DEFAULT_MODELS.get(provider, "gpt-4o-mini")
        return provider, api_key, base_url, model

    provider = (settings.get("llm_provider") or "openai").strip().lower()
    api_key = settings.get("llm_api_key") or settings.get("openai_api_key") or ""
    base_url = settings.get("llm_base_url") or ""
    model = override_model or (settings.get("llm_model") or "").strip() or DEFAULT_MODELS.get(provider, "gpt-4o-mini")
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


def _build_response_cards(*, query: str, query_plan: dict[str, Any] | None, matches: list[AgentModMatch]) -> dict[str, list[str]]:
    plan = query_plan or {}
    filters: list[str] = []
    games = [str(v) for v in (plan.get("games") or []) if str(v).strip()]
    categories = [str(v) for v in (plan.get("categories") or []) if str(v).strip()]
    sources = [str(v) for v in (plan.get("sources") or []) if str(v).strip()]
    if games:
        filters.append(f"游戏：{', '.join(games[:3])}")
    category_markers = ["类型", "分类", "category", "cate", "风格", "画面", "服装", "动作", "任务", "mod type"]
    query_lower = (query or "").lower()
    should_show_categories = any(marker in query_lower for marker in category_markers)
    if categories and should_show_categories:
        filters.append(f"类型：{', '.join(categories[:3])}")
    if sources:
        filters.append(f"来源：{', '.join(sources[:3])}")
    adult = plan.get("adult_content")
    if isinstance(adult, bool):
        filters.append(f"内容分级：{'NSFW' if adult else 'SFW'}")
    sort_field = str(plan.get("sort_field") or "").strip()
    sort_order = str(plan.get("sort_order") or "desc").strip().lower()
    if sort_field:
        sort_labels = {
            "updated_at_remote": "最近更新",
            "first_seen_at": "最近收录",
            "created_at_remote": "创建时间",
            "published_at_remote": "发布时间",
            "downloads": "下载量",
            "unique_downloads": "唯一下载量",
            "endorsements": "点赞/背书",
            "views": "浏览量",
            "likes": "喜欢数",
            "relevance": "相关性",
        }
        sort_label = sort_labels.get(sort_field, sort_field)
        filters.append(f"排序：{sort_label} ({'升序' if sort_order == 'asc' else '降序'})")

    understanding = [f"我理解你想找：{query}"]
    results = [f"找到 {len(matches)} 个候选，优先推荐前 {min(3, len(matches))} 个。"] if matches else ["当前没有命中结果。"]
    if matches:
        for idx, item in enumerate(matches[:3], start=1):
            results.append(f"{idx}. {item.title}（{item.source} / {item.game}）")
    next_steps = (
        ["你可以继续指定：游戏、来源、时间范围、下载量阈值，或让我展开某个 Mod 的详细解析。"]
        if matches
        else ["请补充游戏名、来源或分类后再试，例如：最近更新的 Stellar Blade 画面 Mod。"]
    )
    return {
        "understanding": understanding,
        "filters": filters,
        "results": results,
        "next_steps": next_steps,
    }


@router.post("/chat", response_model=AgentChatResponse)
async def chat_with_agent(
    body: AgentChatRequest,
    request: Request,
    session: SessionDep,
):
    query = body.message.strip()
    if not query:
        return AgentChatResponse(
            answer="请输入要查询的内容。",
            used_llm=False,
            matches=[],
            response_cards={
                "understanding": ["请先输入你的查询需求。"],
                "filters": [],
                "results": ["当前没有可用结果。"],
                "next_steps": ["例如：最近更新的 Stellar Blade 画面 Mod。"],
            },
        )

    matches: list[AgentModMatch] = []

    settings = SettingsService(session)
    await _enforce_rate_limit(_build_rate_limit_key(request, settings))
    provider, api_key, base_url, model = _get_llm_config(
        settings,
        provider_override=body.provider_override,
        model_override=body.model_override,
    )
    llm_available = provider == "ollama" or bool(api_key.strip())

    slot_options = _load_slot_options(session)
    database_schema = _build_database_schema_text(session)
    raw_query_plan = None
    if llm_available:
        raw_query_plan = await _plan_query_with_llm(
            query=query,
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            history=body.history,
            database_schema=database_schema,
            slot_options=slot_options,
        )
    if raw_query_plan is None:
        fallback_tokens = [
            token
            for token in re.split(r"[^\w\u4e00-\u9fff]+", query.lower())
            if token and token not in {"mod", "mods", "模组", "成人", "非成人"}
        ]
        raw_query_plan = {
            "intent": "recent" if _is_recent_query(query) else "search",
            "keywords": fallback_tokens[:5],
            "adult_content": _detect_adult_constraint(query),
            "sort_field": "updated_at_remote" if _is_recent_query(query) else "relevance",
            "sort_order": "desc",
            "limit": DEFAULT_AGENT_LIMIT,
        }

    query_plan = _normalize_query_plan(raw_query_plan, query, slot_options)
    rescored = _query_mods_with_plan(session, query, query_plan)
    if rescored:
        top = rescored[: int(query_plan["limit"])]
        mod_ids = [mod.id for _, mod in top if mod.id is not None]
        summary_by_mod = _build_summary_map(session, mod_ids)
        matches = [
            AgentModMatch(
                id=mod.id or 0,
                title=mod.title,
                source=mod.source,
                game=mod.game,
                game_domain=mod.game_domain,
                category=mod.category,
                author=mod.author,
                version=mod.version,
                url=mod.url,
                updated_at_remote=mod.updated_at_remote,
                downloads=mod.downloads,
                endorsements=mod.endorsements,
                likes=mod.likes,
                adult_content=mod.adult_content,
                score=score,
                original_summary=mod.original_summary,
                translated_summary=summary_by_mod.get(mod.id or 0),
            )
            for score, mod in top
        ]
        if llm_available:
            matches = await _validate_matches_with_llm(
                query=query,
                matches=matches,
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                query_plan=query_plan,
            )
    final_adult_constraint = query_plan.get("adult_content")
    if isinstance(final_adult_constraint, bool):
        matches = [item for item in matches if bool(item.adult_content) == final_adult_constraint]
    if not matches:
        retry_plan = dict(query_plan)
        retry_plan["keywords"] = []
        retry_plan["sort_field"] = query_plan.get("sort_field") or "updated_at_remote"
        retry_plan["sort_order"] = query_plan.get("sort_order") or "desc"
        retry_plan["limit"] = int(query_plan.get("limit") or DEFAULT_AGENT_LIMIT)
        retry_rescored = _query_mods_with_plan(session, query, retry_plan)
        if retry_rescored:
            retry_top = retry_rescored[: int(retry_plan["limit"])]
            retry_ids = [mod.id for _, mod in retry_top if mod.id is not None]
            retry_summary_by_mod = _build_summary_map(session, retry_ids)
            retry_matches = [
                AgentModMatch(
                    id=mod.id or 0,
                    title=mod.title,
                    source=mod.source,
                    game=mod.game,
                    game_domain=mod.game_domain,
                    category=mod.category,
                    author=mod.author,
                    version=mod.version,
                    url=mod.url,
                    updated_at_remote=mod.updated_at_remote,
                    downloads=mod.downloads,
                    endorsements=mod.endorsements,
                    likes=mod.likes,
                    adult_content=mod.adult_content,
                    score=score,
                    original_summary=mod.original_summary,
                    translated_summary=retry_summary_by_mod.get(mod.id or 0),
                )
                for score, mod in retry_top
            ]
            if isinstance(final_adult_constraint, bool):
                retry_matches = [item for item in retry_matches if bool(item.adult_content) == final_adult_constraint]
            if retry_matches:
                matches = retry_matches
    if not matches:
        return AgentChatResponse(
            answer="没有找到明确匹配。我可以先给你“最近更新”列表，或按游戏名/作者名筛选。比如：最近更新的 Skyrim Mod。",
            used_llm=False,
            matches=[],
            response_cards=_build_response_cards(query=query, query_plan=query_plan, matches=[]),
        )
    fallback_answer = "找到以下相关 Mod：\n" + "\n".join([f"- {item.title} ({item.source})" for item in matches])
    if not llm_available:
        return AgentChatResponse(
            answer=fallback_answer,
            used_llm=False,
            matches=matches,
            response_cards=_build_response_cards(query=query, query_plan=query_plan, matches=matches),
        )

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
            f"game_domain={item.game_domain or 'unknown'}; category={item.category or 'unknown'}; "
            f"adult_content={item.adult_content}; downloads={item.downloads}; endorsements={item.endorsements}; "
            f"likes={item.likes}; author={item.author or 'unknown'}; version={item.version or 'unknown'}; url={item.url}"
        )
    prompt = "\n".join(prompt_lines)

    client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
    content = await client.chat(prompt, model=model, max_tokens=500)
    if not content.strip():
        return AgentChatResponse(
            answer=fallback_answer,
            used_llm=False,
            matches=matches,
            response_cards=_build_response_cards(query=query, query_plan=query_plan, matches=matches),
        )
    return AgentChatResponse(
        answer=content.strip(),
        used_llm=True,
        matches=matches,
        response_cards=_build_response_cards(query=query, query_plan=query_plan, matches=matches),
        llm_provider=provider,
        llm_model=model,
    )


@router.post("/mod-detail", response_model=AgentChatResponse)
async def ask_mod_detail(
    body: AgentModDetailRequest,
    request: Request,
    session: SessionDep,
):
    mod = session.get(Mod, body.mod_id)
    if mod is None:
        return AgentChatResponse(
            answer="未找到该 Mod。",
            used_llm=False,
            matches=[],
            response_cards={
                "understanding": ["未找到对应 Mod。"],
                "filters": [],
                "results": ["当前没有可展示的详情结果。"],
                "next_steps": ["请返回结果列表重新选择一个 Mod。"],
            },
        )

    summary_by_mod = _build_summary_map(session, [body.mod_id])
    match = AgentModMatch(
        id=mod.id or 0,
        title=mod.title,
        source=mod.source,
        game=mod.game,
        game_domain=mod.game_domain,
        category=mod.category,
        author=mod.author,
        version=mod.version,
        url=mod.url,
        updated_at_remote=mod.updated_at_remote,
        downloads=mod.downloads,
        endorsements=mod.endorsements,
        likes=mod.likes,
        adult_content=mod.adult_content,
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
    await _enforce_rate_limit(_build_rate_limit_key(request, settings))
    provider, api_key, base_url, model = _get_llm_config(
        settings,
        provider_override=body.provider_override,
        model_override=body.model_override,
    )
    llm_available = provider == "ollama" or bool(api_key.strip())
    if not llm_available:
        return AgentChatResponse(
            answer=fallback,
            used_llm=False,
            matches=[match],
            response_cards={
                "understanding": [f"你希望我详细解析：{mod.title}"],
                "filters": [f"来源：{mod.source}", f"游戏：{mod.game}"],
                "results": [f"已提供该 Mod 的详细信息（{mod.title}）。"],
                "next_steps": ["你可以继续问：兼容性、安装风险、适合人群。"],
            },
        )

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
        f"game_domain={mod.game_domain or ''}",
        f"category={mod.category or ''}",
        f"adult_content={mod.adult_content}",
        f"downloads={mod.downloads}",
        f"endorsements={mod.endorsements}",
        f"likes={mod.likes}",
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
        return AgentChatResponse(
            answer=fallback,
            used_llm=False,
            matches=[match],
            response_cards={
                "understanding": [f"你希望我详细解析：{mod.title}"],
                "filters": [f"来源：{mod.source}", f"游戏：{mod.game}"],
                "results": [f"已提供该 Mod 的详细信息（{mod.title}）。"],
                "next_steps": ["你可以继续问：兼容性、安装风险、适合人群。"],
            },
        )
    return AgentChatResponse(
        answer=content.strip(),
        used_llm=True,
        matches=[match],
        response_cards={
            "understanding": [f"你希望我详细解析：{mod.title}"],
            "filters": [f"来源：{mod.source}", f"游戏：{mod.game}"],
            "results": [f"已生成该 Mod 的详细解析（{mod.title}）。"],
            "next_steps": ["你可以继续问：安装步骤、前置依赖、同类替代 Mod。"],
        },
        llm_provider=provider,
        llm_model=model,
    )


@router.get("/conversation-state", response_model=AgentConversationState)
async def get_conversation_state(
    session: SessionDep,
):
    settings = SettingsService(session)
    return _load_conversation_state(session, settings)


@router.post("/conversation-state", response_model=AgentConversationState)
async def save_conversation_state(
    body: AgentConversationStateSaveRequest,
    session: SessionDep,
):
    settings = SettingsService(session)
    now = datetime.now(UTC).isoformat()
    active_session = body.active_session_id.strip() or _new_session_id()
    last_update_key = f"{AGENT_CHAT_LAST_UPDATE_PREFIX}{active_session}"
    incoming_updated_at = _parse_utc_timestamp(body.client_updated_at)
    if body.client_updated_at and incoming_updated_at is None:
        raise HTTPException(status_code=422, detail="client_updated_at must be ISO timestamp")
    persisted_updated_at = _parse_utc_timestamp(settings.get(last_update_key))
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
    # Keep the newest messages within a bounded total text size to avoid
    # unbounded growth of the persisted conversation payload in agent_messages.
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
    return _load_conversation_state(session, settings)


@router.post("/conversation/new", response_model=AgentConversationNewResponse)
async def start_new_conversation(
    session: SessionDep,
):
    settings = SettingsService(session)
    session_id = _new_session_id()
    settings.set(AGENT_CHAT_ACTIVE_SESSION_KEY, session_id)
    return AgentConversationNewResponse(session_id=session_id)

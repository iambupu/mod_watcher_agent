import json
import re
from typing import Any

from sqlalchemy import inspect as sqlalchemy_inspect
from sqlmodel import Session, select

from app.models.mod import Mod
from app.services.agent.history import compress_history
from app.services.agent.schemas import AgentHistoryItem
from app.services.agent.semantic_search import (
    category_match_score,
    infer_categories,
    semantic_query,
)
from app.services.game_alias_service import (
    add_game_alias_mappings,
    alias_key,
    build_resolved_aliases,
)
from app.services.llm_client import create_llm_client

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


def safe_json_loads(text: str) -> dict | None:
    """处理当前模块的业务逻辑并返回结果。"""
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


def is_recent_query(query: str) -> bool:
    """判断条件是否成立。"""
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


def detect_adult_constraint(query: str) -> bool | None:
    """处理当前模块的业务逻辑并返回结果。"""
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


def build_fallback_query_plan(query: str) -> dict[str, Any]:
    """构建后续流程需要的数据结构。"""
    fallback_tokens = [
        token
        for token in re.split(r"[^\w\u4e00-\u9fff]+", query.lower())
        if token and token not in {"mod", "mods", "模组", "成人", "非成人"}
    ]
    return {
        "intent": "recent" if is_recent_query(query) else "search",
        "keywords": fallback_tokens[:5],
        "adult_content": detect_adult_constraint(query),
        "sort_field": "updated_at_remote" if is_recent_query(query) else "relevance",
        "sort_order": "desc",
        "limit": DEFAULT_AGENT_LIMIT,
    }


def _field_description(table: str, column: str) -> str:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return FIELD_DESCRIPTIONS.get(table, {}).get(column, "当前仅作为数据库字段参与查询/展示")


def build_database_schema_text(session: Session) -> str:
    """构建后续流程需要的数据结构。"""
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
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    rows = session.exec(
        select(column)
        .where(column.is_not(None), column != "")
        .distinct()
        .order_by(column)
        .limit(limit)
    ).all()
    return [str(value).strip() for value in rows if str(value or "").strip()]


def load_slot_options(session: Session) -> dict[str, list[str]]:
    """加载配置或持久化数据。"""
    return {
        "games": _distinct_non_empty_values(session, Mod.game),
        "game_domains": _distinct_non_empty_values(session, Mod.game_domain),
        "categories": _distinct_non_empty_values(session, Mod.category),
        "sources": _merge_unique(_distinct_non_empty_values(session, Mod.source), ["nexusmods", "loverslab"]),
    }


def _format_slot_options(options: dict[str, list[str]]) -> str:
    """格式化内部展示或通知文本。"""
    lines = []
    for key in ["games", "game_domains", "categories", "sources"]:
        values = options.get(key, [])
        lines.append(f"{key}: {json.dumps(values, ensure_ascii=False)}")
    return "\n".join(lines)


def _merge_unique(values: list[str], additions: list[str]) -> list[str]:
    """合并多个来源的数据并保持稳定顺序。"""
    merged = list(values)
    seen = set(values)
    for item in additions:
        if item not in seen:
            merged.append(item)
            seen.add(item)
    return merged


def _infer_allowed_values_from_text(text: str, aliases: dict[str, list[str]]) -> list[str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
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
    """规范化内部数据，供后续流程使用。"""
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
    """规范化内部数据，供后续流程使用。"""
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


def _extract_scope_constraints(query: str) -> dict[str, str]:
    """从查询末尾的 [scope] 块读取前端强制约束。"""

    marker = "[scope]"
    if marker not in query:
        return {}
    _, scope_text = query.split(marker, 1)
    constraints: dict[str, str] = {}
    for line in scope_text.splitlines():
        key, sep, value = line.partition("=")
        if sep != "=":
            continue
        key = key.strip().lower()
        value = value.strip()
        if key in {"source", "game", "sort_field"} and value:
            constraints[key] = value
    return constraints


def _apply_scope_overrides(
    raw: dict[str, Any],
    query: str,
    slot_options: dict[str, list[str]],
) -> dict[str, Any]:
    """让显式 scope 约束覆盖 LLM 计划，保证页面来源和游戏过滤不漂移。"""

    scope = _extract_scope_constraints(query)
    if not scope:
        return raw
    scoped = dict(raw)
    if scope.get("source"):
        scoped["sources"] = [scope["source"]]
    if scope.get("sort_field"):
        scoped["sort_field"] = scope["sort_field"]
    scoped_game = scope.get("game")
    if scoped_game:
        domain_keys = {alias_key(value): value for value in slot_options["game_domains"]}
        game_key = alias_key(scoped_game)
        if game_key in domain_keys:
            scoped["game_domains"] = [domain_keys[game_key]]
        else:
            scoped["games"] = [scoped_game]
    return scoped


def _normalize_intent(raw: dict[str, Any]) -> str:
    """把未知 intent 收敛为 search，避免下游分支处理未定义值。"""

    intent = str(raw.get("intent") or "search").strip().lower()
    if intent not in {"recent", "search", "author", "game", "unknown"}:
        return "search"
    return intent


def _normalize_keywords_and_games(
    raw: dict[str, Any],
    query: str,
    slot_options: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    """解析游戏别名，并从关键词中移除已经被识别为游戏的词。"""

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
    games = _normalize_allowed_list(raw.get("games") or raw.get("game"), slot_options["games"], game_aliases)
    return keywords, _merge_unique(games, inferred_games)


def _normalize_adult_content(query: str) -> bool | None:
    """只信任用户原文中的成人内容标记，忽略 LLM 对 adult_content 的猜测。"""

    return detect_adult_constraint(query)


def _normalize_limit(raw: dict[str, Any]) -> int:
    """把 limit 限制在 Agent 查询允许的范围内。"""

    try:
        limit = int(raw.get("limit") or DEFAULT_AGENT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_AGENT_LIMIT
    return max(1, min(MAX_AGENT_LIMIT, limit))


def _normalize_categories(
    raw: dict[str, Any],
    query: str,
    slot_options: dict[str, list[str]],
) -> tuple[list[str], str, list[str]]:
    """合并 LLM 分类和语义分类；特定关键词查询会丢弃过宽的 LLM 分类猜测。"""

    explicit_categories = _normalize_allowed_list(
        raw.get("categories") or raw.get("category"),
        slot_options["categories"],
    )
    explicit_semantic = semantic_query(query)
    if explicit_categories and explicit_semantic.all_terms and not explicit_semantic.category_aliases:
        explicit_categories = []
    if explicit_categories and explicit_semantic.category_aliases:
        semantic_matched_categories = [
            category
            for category in explicit_categories
            if category_match_score(category, explicit_semantic) > 0
        ]
        if semantic_matched_categories:
            explicit_categories = semantic_matched_categories
    categories = list(explicit_categories)
    categories = infer_categories(query, slot_options["categories"], categories)
    category_match_mode = "exact" if explicit_categories else "db_fuzzy"
    semantic = semantic_query(query, categories)
    return categories, category_match_mode, semantic.expanded_terms


def normalize_query_plan(plan: dict | None, query: str, slot_options: dict[str, list[str]]) -> dict[str, Any]:
    """将 LLM 或兜底生成的查询计划规范化为数据库查询可消费的结构。"""

    raw = plan if isinstance(plan, dict) else {}
    raw = _apply_scope_overrides(raw, query, slot_options)
    intent = _normalize_intent(raw)
    keywords, games = _normalize_keywords_and_games(raw, query, slot_options)
    categories, category_match_mode, semantic_keywords = _normalize_categories(raw, query, slot_options)
    keywords = _merge_unique(keywords, semantic_keywords)

    return {
        "intent": intent,
        "keywords": keywords[:10],
        "games": games,
        "game_domains": _normalize_allowed_list(raw.get("game_domains") or raw.get("game_domain"), slot_options["game_domains"]),
        "categories": categories,
        "category_match_mode": category_match_mode,
        "sources": _normalize_allowed_list(raw.get("sources") or raw.get("source"), slot_options["sources"]),
        "adult_content": _normalize_adult_content(query),
        "sort_field": _normalize_sort_field(raw.get("sort_field") or raw.get("sort"), intent),
        "sort_order": "asc" if str(raw.get("sort_order") or "").strip().lower() == "asc" else "desc",
        "limit": _normalize_limit(raw),
    }


async def plan_query_with_llm(
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
    """处理当前模块的业务逻辑并返回结果。"""
    client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
    history_summary, recent_history = compress_history(history, max_items=8, max_chars=1200)
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
    plan = safe_json_loads(plan_text)
    if not isinstance(plan, dict):
        return None
    return plan

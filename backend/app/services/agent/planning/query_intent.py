import re

from app.services.agent.slot_aliases import SOURCE_ALIASES
from app.services.agent.slot_text_inference import (
    infer_compatibility_terms,
    infer_excluded_keywords,
    infer_requirement_terms,
)


def is_recent_query(query: str) -> bool:
    """Return whether the query asks for recent/updated mod results."""
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
    mod_words = ["mod", "mods", "模组", "preset", "presets", "body", "outfit", "armor", "weapon", "plugin", "plugins"]
    has_recent = any(word in q for word in recent_words)
    has_mod = any(word in q for word in mod_words)
    return has_recent and has_mod


def detect_query_intent(query: str) -> str:
    """Classify high-level user intent before slot normalization."""
    q = (query or "").lower()
    comparison_markers = [
        "哪个",
        "哪一个",
        "对比",
        "比较一下",
        "做个比较",
        "比较这",
        "这两个",
        "两个哪个",
        "更适合",
        "更推荐",
        "风险更低",
        "which",
        "compare",
        "comparison",
        "better",
        "lower risk",
        "less risky",
    ]
    if any(marker in q for marker in comparison_markers):
        return "comparison"
    explicit_alternative_markers = [
        "替代",
        "替代品",
        "平替",
        "换一个",
        "换一批",
        "alternative",
        "replacement",
        "substitute",
        "instead",
    ]
    if any(marker in q for marker in explicit_alternative_markers):
        return "alternative"
    recommendation_markers = [
        "推荐",
        "推荐几个",
        "推荐一些",
        "好用",
        "值得装",
        "best",
        "recommend",
        "recommended",
        "suggest",
        "suggestion",
    ]
    if any(marker in q for marker in recommendation_markers):
        return "preference_summary"
    alternative_preference_markers = [
        "更稳",
        "更安全",
        "更合适",
        "更兼容",
        "safer",
        "more stable",
        "more compatible",
    ]
    if any(marker in q for marker in alternative_preference_markers):
        return "alternative"
    if _is_constraint_search_query(query) or _is_negative_constraint_search_query(query) or _is_gameplay_support_search(query):
        return "search"
    risk_markers = [
        "安装风险",
        "风险",
        "前置",
        "依赖",
        "兼容",
        "支持",
        "适配",
        "冲突",
        "会不会坏",
        "装了会",
        "install risk",
        "requirements",
        "requirement",
        "dependency",
        "dependencies",
        "compatible",
        "compatibility",
        "support",
        "supports",
        "conflict",
        "load order",
    ]
    if any(marker in q for marker in risk_markers):
        return "install_risk"
    if any(marker in q for marker in ["偏好", "收藏", "喜欢", "preference", "favorite"]):
        return "preference_summary"
    if is_recent_query(query):
        return "recent"
    return "search"


def detect_adult_constraint(query: str) -> bool | None:
    """Infer an explicit adult-content constraint from query text."""
    q = (query or "").lower()
    if not q:
        return None
    negative_markers = [
        "不要成人内容",
        "不要成人",
        "不要 nsfw",
        "不要 r18",
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


def infer_source_constraints(query: str) -> dict[str, list[str]]:
    """Infer source include/exclude constraints from natural language."""
    q = (query or "").lower()
    included: list[str] = []
    excluded: list[str] = []
    for alias, source in SOURCE_ALIASES.items():
        if not _source_alias_in_text(q, alias):
            continue
        if _source_alias_is_excluded(q, alias):
            excluded = _merge_unique(excluded, [source])
        else:
            included = _merge_unique(included, [source])
    constraints: dict[str, list[str]] = {}
    if included:
        constraints["sources"] = included
    if excluded:
        constraints["excluded_sources"] = excluded
    return constraints


def infer_sort_preference(query: str) -> dict[str, str]:
    """Infer sort field/order from common natural-language ranking requests."""
    q = (query or "").lower()
    ascending = any(marker in q for marker in ["最少", "最低", "least", "lowest", "fewest", "ascending", "asc"])
    sort_order = "asc" if ascending else "desc"
    if is_recent_query(query):
        return {"sort_field": "updated_at_remote", "sort_order": sort_order}
    sort_markers = [
        (["唯一下载", "unique download", "unique downloads"], "unique_downloads"),
        (["背书", "点赞", "endorsement", "endorsements", "endorsed", "endorse"], "endorsements"),
        (["下载", "download", "downloads", "downloaded"], "downloads"),
        (["喜欢", "like", "likes"], "likes"),
        (["浏览", "浏览量", "view", "views"], "views"),
        (["发布", "published"], "published_at_remote"),
        (["创建", "created"], "created_at_remote"),
    ]
    for markers, field in sort_markers:
        if any(_marker_in_text(marker, q) for marker in markers):
            return {"sort_field": field, "sort_order": sort_order}
    if not is_recent_query(query) and any(marker in q for marker in ["热门", "火", "popular", "popularity", "top", "most"]):
        return {"sort_field": "downloads", "sort_order": sort_order}
    return {}


def _is_constraint_search_query(query: str) -> bool:
    if _has_strong_risk_or_reference(query):
        return False
    has_constraint = bool(infer_requirement_terms(query) or infer_compatibility_terms(query))
    return has_constraint and _has_search_marker(query)


def _is_negative_constraint_search_query(query: str) -> bool:
    if _has_strong_risk_or_reference(query):
        return False
    exclusions = infer_excluded_keywords(query).get("excluded_keywords") or []
    if not exclusions:
        return False
    q = (query or "").lower()
    has_negative_constraint_marker = any(
        marker in q
        for marker in [
            "不需要",
            "无需",
            "不依赖",
            "不要依赖",
            "不要求",
            "不支持",
            "不兼容",
            "不适配",
            "without",
            "not compatible",
            "does not support",
            "doesn't support",
        ]
    )
    if not has_negative_constraint_marker:
        has_negative_constraint_marker = re.search(
            r"\b(?:without|no)\s+[^,?.\n]{1,80}\s+(?:requirement|requirements|dependency|dependencies)\b",
            q,
        ) is not None
    return has_negative_constraint_marker and _has_search_marker(query)


def _has_strong_risk_or_reference(query: str) -> bool:
    q = (query or "").lower()
    strong_risk_markers = [
        "安装风险",
        "风险",
        "冲突",
        "会不会",
        "装了会",
        "坏",
        "risk",
        "conflict",
        "load order",
    ]
    if any(marker in q for marker in strong_risk_markers):
        return True
    return bool(any(marker in q for marker in ["这个", "它", "该"]) or re.search(r"\b(?:this|it|that)\b", q))


def _has_search_marker(query: str) -> bool:
    q = (query or "").lower()
    search_markers = [
        "mod",
        "mods",
        "模组",
        "插件",
        "找",
        "有哪些",
        "有",
        "show",
        "list",
        "find",
    ]
    return any(marker in q for marker in search_markers)


def _is_gameplay_support_search(query: str) -> bool:
    q = (query or "").lower()
    if not q or not _has_search_marker(query):
        return False
    has_support_marker = any(marker in q for marker in ["支持", "support", "supports"])
    has_gameplay_marker = any(marker in q for marker in ["玩法", "机制", "gameplay", "roleplay", "扮演"])
    return has_support_marker and has_gameplay_marker


def _marker_in_text(marker: str, text: str) -> bool:
    if re.fullmatch(r"[a-z0-9 ]+", marker):
        return re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text, flags=re.IGNORECASE) is not None
    return marker in text


def _source_alias_is_excluded(text: str, alias: str) -> bool:
    for match in re.finditer(_source_alias_pattern(alias), text):
        window = text[max(0, match.start() - 24) : match.start()]
        parts = re.split(r"[，,。.!?；;：:\n]", window)
        window = parts[-1] if parts else window
        if any(
            marker in window
            for marker in [
                "不要",
                "排除",
                "不看",
                "别看",
                "除了",
                "除外",
                "not from",
                "not ",
                "exclude",
                "excluding",
                "except",
                "without",
                "no ",
            ]
        ):
            return True
    return False


def _source_alias_in_text(text: str, alias: str) -> bool:
    return re.search(_source_alias_pattern(alias), text) is not None


def _source_alias_pattern(alias: str) -> str:
    alias = alias.lower()
    if re.fullmatch(r"[a-z0-9]+", alias):
        return rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
    return re.escape(alias)


def _merge_unique(values: list[str], additions: list[str]) -> list[str]:
    result = list(values)
    seen = {str(value).strip().lower() for value in result}
    for value in additions:
        token = str(value).strip()
        key = token.lower()
        if token and key not in seen:
            result.append(token)
            seen.add(key)
    return result

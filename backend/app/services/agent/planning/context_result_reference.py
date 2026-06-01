import re
from typing import Any

from app.services.agent.context.context_inference import is_contextual_followup
from app.services.agent.semantic_search import base_keywords


def apply_result_reference_context(raw: dict[str, Any], query: str, shown_mod_titles: list[str] | None) -> None:
    titles = [str(value).strip() for value in (shown_mod_titles or []) if str(value).strip()]
    if not titles:
        return
    applied_fields: list[str] = []
    if is_comparison_followup(query):
        raw["keywords"] = titles[:5]
        applied_fields.append("keywords")
    if is_referenced_alternative_followup(query):
        raw["keywords"] = referenced_title_keywords(_referenced_shown_title(query, titles))
        applied_fields.append("keywords")
    if is_referenced_similarity_followup(query):
        raw["keywords"] = referenced_title_keywords(_referenced_shown_title(query, titles))
        raw["keyword_match_mode"] = "all"
        applied_fields.extend(["keywords", "keyword_match_mode"])
    if is_mod_reference_followup(query):
        referenced_title = _referenced_shown_title(query, titles)
        raw["keywords"] = [referenced_title]
        raw["exact_title"] = referenced_title
        applied_fields.extend(["keywords", "exact_title"])
    if should_avoid_prior_results(query):
        raw["exclude_titles"] = titles
        applied_fields.append("exclude_titles")
    if applied_fields:
        raw["_agent_result_reference_signal"] = {
            "applied": True,
            "fields": list(dict.fromkeys(applied_fields)),
            "titles": titles[:5],
            "has_explicit_reference": _has_reference(query),
        }


def is_contextual_query_followup(query: str) -> bool:
    lowered = query.lower()
    return (
        is_contextual_followup(lowered)
        or any(marker in lowered for marker in (_ALTERNATIVE_MARKERS | _COMPARISON_MARKERS))
        or any(
            marker in lowered
            for marker in {
                "similar",
                "related",
                "more like",
                "like this",
                "ones",
                "same style",
                "same vibe",
            }
        )
    )


def is_comparison_followup(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in _COMPARISON_MARKERS)


def is_mod_reference_followup(query: str) -> bool:
    lowered = query.lower()
    has_reference = _has_reference(query)
    has_detail_intent = any(
        marker in lowered
        for marker in {
            "风险",
            "安装",
            "前置",
            "依赖",
            "兼容",
            "冲突",
            "risk",
            "install",
            "requirement",
            "dependency",
            "compatible",
            "compatibility",
            "conflict",
        }
    )
    return has_reference and has_detail_intent


def is_referenced_alternative_followup(query: str) -> bool:
    lowered = query.lower()
    return _has_reference(query) and any(marker in lowered for marker in _ALTERNATIVE_MARKERS)


def is_referenced_similarity_followup(query: str) -> bool:
    lowered = query.lower()
    if (
        not _has_reference(query)
        or is_referenced_alternative_followup(query)
        or is_mod_reference_followup(query)
    ):
        return False
    return any(marker in lowered for marker in {"相关", "类似", "同类", "同款", "same", "similar", "related"})


def referenced_title_keywords(title: str) -> list[str]:
    title_keywords = [
        keyword
        for keyword in base_keywords(title)
        if keyword not in {"mod", "mods", "模组"}
    ]
    return list(dict.fromkeys(title_keywords))[:5]


def should_avoid_prior_results(query: str) -> bool:
    lowered = query.lower()
    return any(
        marker in lowered
        for marker in {
            "还有",
            "其他",
            "再找",
            "类似",
            "同类",
            "换一批",
            "不要重复",
            "别重复",
            "more",
            "other",
            "another",
            "different",
            "similar",
            "related",
        }
        | _ALTERNATIVE_MARKERS
    )


def shown_titles_from_history(history: list | None) -> list[str]:
    if not history:
        return []
    titles: list[str] = []
    for item in reversed(history):
        if str(getattr(item, "role", "")).strip() != "assistant":
            continue
        text = str(getattr(item, "text", "") or "")
        for title in _title_candidates_from_assistant_text(text):
            if title not in titles:
                titles.append(title)
        if titles:
            return titles[:5]
    return []


def _has_reference(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in {"这个", "它", "该", "this", "it"}) or _referenced_index(query) is not None


def _referenced_shown_title(query: str, titles: list[str]) -> str:
    index = _referenced_index(query)
    if index is not None and 0 <= index < len(titles):
        return titles[index]
    return titles[0]


def _referenced_index(query: str) -> int | None:
    normalized = str(query or "").lower()
    for pattern in [
        r"第\s*([一二三四五六七八九十\d]+)\s*(?:个|条|项|款)?",
        r"\b(?:no\.?|#)\s*(\d+)\b",
        r"\b(?:the\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b",
    ]:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match:
            continue
        number = _ordinal_number(match.group(1))
        if number is not None and number > 0:
            return number - 1
    return None


def _title_candidates_from_assistant_text(text: str) -> list[str]:
    candidates: list[str] = []
    for pattern in [
        r"(?:找到了|找到|展示|推荐)\s*([A-Z][A-Za-z0-9][A-Za-z0-9 '&:_-]{2,80})",
        r"\b([A-Z][A-Za-z0-9]+(?:[ '&:_-]+[A-Z][A-Za-z0-9]+){1,8})\b",
    ]:
        for match in re.finditer(pattern, text):
            title = match.group(1).strip(" 。.,，")
            if title and title.lower() not in {"i found", "here are"}:
                candidates.append(title)
    return candidates


def _ordinal_number(value: str) -> int | None:
    token = str(value or "").strip().lower()
    if token.isdigit():
        return int(token)
    english = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "sixth": 6,
        "seventh": 7,
        "eighth": 8,
        "ninth": 9,
        "tenth": 10,
    }
    if token in english:
        return english[token]
    chinese = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return chinese.get(token)


_ALTERNATIVE_MARKERS = {
    "替代",
    "替代品",
    "平替",
    "换一个",
    "换一批",
    "更稳",
    "更安全",
    "更合适",
    "alternative",
    "replacement",
    "substitute",
    "instead",
    "safer",
    "more stable",
    "more compatible",
}

_COMPARISON_MARKERS = {
    "哪个",
    "哪一个",
    "对比",
    "比较",
    "更适合",
    "更推荐",
    "风险更低",
    "新手",
    "which",
    "compare",
    "comparison",
    "better",
    "recommend",
    "beginner",
    "lower risk",
    "less risky",
}

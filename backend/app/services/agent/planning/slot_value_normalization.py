import re
from typing import Any

from app.services.agent.identity_inference import source_from_url
from app.services.agent.list_utils import merge_unique_text, unique_text
from app.services.agent.planning.query_intent import _is_gameplay_support_search
from app.services.agent.semantic_search import semantic_query
from app.services.agent.slot_aliases import SUMMARY_LANGUAGE_ALIASES
from app.services.agent.slot_text_inference import (
    clean_author_value,
    clean_exact_title,
    clean_excluded_phrase,
    clean_version_value,
    split_compatibility_terms,
    split_requirement_terms,
)
from app.services.game_alias_service import alias_key


def normalize_author(raw: Any) -> str | None:
    if isinstance(raw, str):
        return clean_author_value(raw)
    return None


def normalize_exact_title(raw: Any) -> str | None:
    if isinstance(raw, str):
        return clean_exact_title(raw)
    return None


def normalize_version(raw: Any) -> str | None:
    if isinstance(raw, str | int | float):
        return clean_version_value(str(raw))
    return None


def normalize_source_url(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if not value.lower().startswith(("http://", "https://")):
        value = f"https://{value}"
    return value if source_from_url(value) else None


def normalize_excluded_keywords(raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list | tuple | set):
        values = list(raw)
    else:
        return []
    normalized: list[str] = []
    for value in values:
        phrase = clean_excluded_phrase(str(value or ""))
        if not phrase:
            continue
        semantic = semantic_query(phrase)
        normalized = merge_unique_text(
            normalized,
            [*semantic.base_keywords, *semantic.category_aliases],
            key_func=alias_key,
        )
    return normalized[:10]


def normalize_tags(raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = _split_tag_values(raw)
    elif isinstance(raw, list | tuple | set):
        values = []
        for value in raw:
            values.extend(_split_tag_values(str(value or "")))
    else:
        return []
    return _normalize_unique_terms(values, limit=10)


def has_explicit_tag_constraint(query: str) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    return bool(
        re.search(r"\btag(?:s|ged)?\b", text, flags=re.IGNORECASE)
        or re.search(r"标签|标记", text)
    )


def normalize_requirement_terms(raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = split_requirement_terms(raw)
    elif isinstance(raw, list | tuple | set):
        values = []
        for value in raw:
            values.extend(split_requirement_terms(str(value or "")))
    else:
        return []
    return _normalize_unique_terms(values, limit=10)


def normalize_compatibility_terms(raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = split_compatibility_terms(raw)
    elif isinstance(raw, list | tuple | set):
        values = []
        for value in raw:
            values.extend(split_compatibility_terms(str(value or "")))
    else:
        return []
    return _normalize_unique_terms(values, limit=10)


def drop_gameplay_support_compatibility_terms(query: str, compatibility_terms: list[str]) -> list[str]:
    if not compatibility_terms or not _is_gameplay_support_search(query):
        return compatibility_terms
    capability_keys = {
        alias_key(value)
        for value in [
            "怀孕",
            "pregnancy",
            "pregnant",
            "玩法",
            "gameplay",
            "机制",
            "roleplay",
            "扮演",
            "bimbo",
        ]
    }
    return [
        term
        for term in compatibility_terms
        if not any(key and key in alias_key(term) for key in capability_keys)
    ]


def normalize_summary_languages(raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list | tuple | set):
        values = list(raw)
    else:
        return []
    normalized: list[str] = []
    for value in values:
        key = alias_key(value)
        language = SUMMARY_LANGUAGE_ALIASES.get(str(value or "").strip().lower()) or SUMMARY_LANGUAGE_ALIASES.get(key)
        if not language and str(value or "").strip() in {"zh-CN", "en", "ja-JP"}:
            language = str(value or "").strip()
        if language:
            normalized = merge_unique_text(normalized, [language], key_func=alias_key)
    return normalized[:5]


def drop_excluded_summary_languages(
    summary_languages: list[str],
    excluded_summary_languages: list[str],
) -> list[str]:
    if not excluded_summary_languages:
        return summary_languages
    excluded = set(excluded_summary_languages)
    return [language for language in summary_languages if language not in excluded]


def _split_tag_values(value: str) -> list[str]:
    cleaned = re.split(
        r"(?:\s+的\b|的|\s+(?:but\s+not|but\s+without|without|not|no)\b|\s+(?:and|or)\s+(?:chinese|english|japanese|summary|description|intro|with|from|except|excluding|not|no|without|preview|image|images|thumbnail|screenshot|screenshots|updated|published|created|after|before|at\s+least|downloads?|views?|likes?|endorsements?)\b|(?:\s+)?(?:mod|mods|模组|作品|资源)\b|[，。？?]|$)",
        str(value or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    parts = re.split(r"(?:,|/|、|\s+and\s+|\s+or\s+|\s+和\s+|\s+与\s+)", cleaned, flags=re.IGNORECASE)
    tags: list[str] = []
    blocked = {
        alias_key(value)
        for value in [
            "and",
            "or",
            "with",
            "tag",
            "tags",
            "tagged",
            "标签",
            "mod",
            "mods",
            "模组",
            "summary",
            "description",
            "intro",
            "chinese summary",
            "english summary",
            "japanese summary",
        ]
    }
    for part in parts:
        tag = re.sub(r"\s+", " ", part).strip(" .:-_")
        lowered = tag.lower()
        if re.match(r"^(?:and|or|from|except|excluding|not|no|without|with)\b", lowered):
            continue
        if re.match(r"^(?:at least|minimum|min|downloads?|views?|likes?|endorsements?)\b", lowered):
            continue
        if tag and alias_key(tag) not in blocked:
            tags.append(tag)
    return tags


def _normalize_unique_terms(values: list[str], *, limit: int) -> list[str]:
    normalized = [re.sub(r"\s+", " ", str(value or "").strip()) for value in values]
    return unique_text(normalized, limit=limit, key_func=alias_key)

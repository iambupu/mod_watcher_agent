import re

from app.services.agent.list_utils import merge_unique_text as _merge_unique
from app.services.agent.semantic_search import strip_scope
from app.services.agent.slot_aliases import SUMMARY_LANGUAGE_ALIASES


def infer_tag_constraints(query: str) -> dict[str, list[str]]:
    """从“带 CBBE 标签”或 `tag: 3BA` 等表达中推断标签过滤条件。"""
    text = strip_scope(query)
    tags: list[str] = []
    patterns = [
        r"(?:标签|tag|tags|tagged)\s*[:：=]?\s*([A-Za-z0-9][A-Za-z0-9_\-+ .,/]{0,80})",
        r"(?:带|包含|含有)\s*([A-Za-z0-9][A-Za-z0-9_\-+ .,/]{0,80})\s*(?:标签|tag|tags)(?:\b|的|$)",
        r"\bwith\s+([A-Za-z0-9][A-Za-z0-9_\-+ .,/]{0,80})\s*(?:标签|tag|tags)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            if _match_has_negative_prefix(text, match.start()):
                continue
            tags = _merge_unique(tags, _split_tag_values(match.group(1)))
    return {"tags": tags[:10]} if tags else {}


def infer_summary_language_constraints(query: str) -> dict[str, list[str]]:
    """推断用户请求的摘要语言，例如中文摘要或英文介绍。"""
    text = strip_scope(query).lower()
    if not any(marker in text for marker in ["摘要", "介绍", "说明", "summary", "intro", "description"]):
        return {}
    languages: list[str] = []
    excluded_languages: list[str] = []
    for alias, language in SUMMARY_LANGUAGE_ALIASES.items():
        alias_text = alias.lower()
        pattern = rf"(?<![a-z0-9]){re.escape(alias_text)}(?![a-z0-9])" if alias_text.isascii() else re.escape(alias_text)
        for match in re.finditer(pattern, text):
            window = text[max(0, match.start() - 24) : min(len(text), match.end() + 24)]
            if not any(marker in window for marker in ["摘要", "介绍", "说明", "summary", "intro", "description"]):
                continue
            if _match_has_negative_prefix(text, match.start()):
                excluded_languages = _merge_unique(excluded_languages, [language])
            else:
                languages = _merge_unique(languages, [language])
    result: dict[str, list[str]] = {}
    if languages:
        result["summary_languages"] = languages[:5]
    if excluded_languages:
        result["excluded_summary_languages"] = excluded_languages[:5]
    return result


def infer_thumbnail_constraint(query: str) -> dict[str, bool]:
    """推断用户是否明确要求有图或无图 MOD。"""
    text = strip_scope(query).lower()
    negative_markers = [
        "不要图片",
        "不要图",
        "不要预览",
        "不要截图",
        "无图",
        "没有图",
        "without image",
        "without images",
        "no image",
        "no images",
        "no thumbnail",
        "no preview",
    ]
    positive_markers = [
        "有图片",
        "有图",
        "带图",
        "有预览",
        "预览图",
        "有截图",
        "截图",
        "封面图",
        "图片",
        "with image",
        "with images",
        "with thumbnail",
        "with preview",
        "screenshot",
        "screenshots",
        "thumbnail",
        "preview image",
    ]
    if any(marker in text for marker in negative_markers):
        return {"has_thumbnail": False}
    if any(marker in text for marker in positive_markers):
        return {"has_thumbnail": True}
    return {}


def query_without_thumbnail_terms(query: str) -> str:
    cleaned = query
    for pattern in [
        r"(?:不要|没有|无|带|有)?\s*(?:图片|图|预览图?|截图|封面图)",
        r"\b(?:with|without|no)\s+(?:images?|thumbnail|preview|screenshots?)\b",
        r"\b(?:images?|thumbnail|preview image|screenshots?)\b",
    ]:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _split_tag_values(value: str) -> list[str]:
    cleaned = re.split(
        r"(?:\s+的\b|的|\s+(?:but\s+not|but\s+without|without|not|no)\b|\s+(?:and|or)\s+(?:chinese|english|japanese|summary|description|intro|with|from|except|excluding|not|no|without|preview|image|images|thumbnail|screenshot|screenshots|updated|published|created|after|before|at\s+least|downloads?|views?|likes?|endorsements?)\b|(?:\s+)?(?:mod|mods|模组|作品|资源)\b|[，。？?]|$)",
        str(value or ""),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    parts = re.split(r"(?:,|/|、|\s+and\s+|\s+or\s+|\s+和\s+|\s+与\s+)", cleaned, flags=re.IGNORECASE)
    blocked = {
        _alias_key(value)
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
    tags: list[str] = []
    for part in parts:
        tag = re.sub(r"\s+", " ", part).strip(" .:-_")
        lowered = tag.lower()
        if re.match(r"^(?:and|or|from|except|excluding|not|no|without|with)\b", lowered):
            continue
        if re.match(r"^(?:at least|minimum|min|downloads?|views?|likes?|endorsements?)\b", lowered):
            continue
        if tag and _alias_key(tag) not in blocked:
            tags.append(tag)
    return tags


def _match_has_negative_prefix(text: str, start: int) -> bool:
    window = text[max(0, start - 24) : start].lower()
    return any(
        marker in window
        for marker in [
            "不要",
            "排除",
            "不看",
            "别看",
            "不带",
            "不含",
            "不",
            "without",
            "no ",
            "exclude",
            "excluding",
            "not ",
        ]
    )


def _alias_key(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())

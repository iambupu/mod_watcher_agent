import re

from app.services.agent.list_utils import merge_unique_text as _merge_unique
from app.services.agent.semantic_search import semantic_query, strip_scope
from app.services.game_alias_service import alias_key


def infer_title_constraint(query: str) -> dict[str, str]:
    """在用户明确点名 MOD 时推断精确标题约束。"""
    text = strip_scope(query)
    for pattern in [
        r"[\"“”']([^\"“”']{2,120})[\"“”']",
        r"(?:called|named|titled|title)\s*[:：=]?\s*[\"“']?([^\"“”'，,。？?\n]{2,120})",
        r"(?:叫|名叫|标题|名字|名称)\s*[:：=]?\s*[\"“']?([^\"“”'，,。？?\n]{2,120})",
    ]:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        title = clean_exact_title(match.group(1))
        if title:
            return {"exact_title": title}
    return {}


def infer_version_constraint(query: str) -> dict[str, str]:
    """推断 `version 1.2.0` 或 `v1.5` 之类的显式版本过滤条件。"""
    text = strip_scope(query)
    patterns = [
        r"(?:version|版本)\s*[:：=]?\s*v?\s*([0-9]+(?:\.[0-9A-Za-z]+){0,4}(?:[-_][0-9A-Za-z]+)?)",
        r"\bv\s*([0-9]+(?:\.[0-9A-Za-z]+){1,4}(?:[-_][0-9A-Za-z]+)?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if version_is_runtime_context(text, match.start()):
            continue
        version = clean_version_value(match.group(1))
        if version:
            return {"version": version}
    return {}


def infer_requirement_terms(query: str) -> dict[str, list[str]]:
    """从安装风险问题中推断明确的依赖或前置名称。"""
    text = strip_scope(query)
    terms: list[str] = []
    patterns = [
        r"(?:需要|依赖|前置|要求)\s*([A-Za-z0-9][A-Za-z0-9_\-+ .]{1,80})(?:\s*(?:前置|依赖|要求))?",
        r"([A-Za-z0-9][A-Za-z0-9_\-+ .]{1,80})\s*(?:前置|依赖)",
        r"\b([A-Za-z0-9][A-Za-z0-9_\-+.]{1,40}(?:\s*(?:/|and|or)\s*[A-Za-z0-9][A-Za-z0-9_\-+.]{1,40})*)\s+(?:requirement|dependency)\b",
        r"\b(?:requires?|requiring|needs?|needed|requirement|requirements|dependencies|dependency)\s+([A-Za-z0-9][A-Za-z0-9_\-+ .]{1,80})",
        r"\b(?:depends?\s+on|dependent\s+on)\s+([A-Za-z0-9][A-Za-z0-9_\-+ .]{1,80})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            if match_has_negative_prefix(text, match.start()):
                continue
            terms = _merge_unique(terms, split_requirement_terms(match.group(1)))
    return {"requirement_terms": terms[:10]} if terms else {}


def infer_compatibility_terms(query: str) -> dict[str, list[str]]:
    """推断 AE、VR 或游戏运行时版本等明确兼容目标。"""
    text = strip_scope(query)
    terms: list[str] = []
    patterns = [
        r"(?:支持|兼容|适配)\s*([A-Za-z0-9][A-Za-z0-9_\-+ .]{0,80})",
        r"([A-Za-z0-9][A-Za-z0-9_\-+ .]{0,80})\s*(?:兼容|适配|支持)",
        r"\b(?:compatible with|supports?|for)\s+([A-Za-z0-9][A-Za-z0-9_\-+ .]{0,80})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            if match_has_negative_prefix(text, match.start()):
                continue
            terms = _merge_unique(terms, split_compatibility_terms(match.group(1)))
    return {"compatibility_terms": terms[:10]} if terms else {}


def query_without_compatibility_terms(query: str) -> str:
    cleaned = query
    for pattern in [
        r"(?:支持|兼容|适配)\s*[A-Za-z0-9][A-Za-z0-9_\-+ .]{0,40}\s*(?:的\b|的)?",
        r"\b(?:compatible with|supports?|for)\s+[A-Za-z0-9][A-Za-z0-9_\-+ .]{0,40}\b",
    ]:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def infer_author_constraint(query: str) -> dict[str, str]:
    """从常见作者限定表达中推断作者或 Modder 名称。"""
    text = strip_scope(query)
    patterns = [
        r"(?:作者是|作者|创作者)\s*[:：=]?\s*([A-Za-z0-9][A-Za-z0-9_\- .]{1,80})",
        r"([A-Za-z0-9][A-Za-z0-9_\- .]{1,80})\s*(?:作者|创作者)\s*的?",
        r"(?:author|creator|modder)\s*[:=]?\s+([A-Za-z0-9][A-Za-z0-9_\- .]{1,80})",
        r"\bby\s+([A-Za-z0-9][A-Za-z0-9_\- .]{1,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        author = clean_author_value(match.group(1))
        if author:
            return {"author": author}
    return {}


def infer_excluded_keywords(query: str) -> dict[str, list[str]]:
    """推断“不要护甲”或 `without armor` 之类的排除关键词。"""
    text = strip_scope(query)
    text = query_without_adult_markers(text)
    phrases: list[str] = []
    for pattern in [
        r"(?:不需要|无需|不依赖|不要依赖|不要求)\s*([^，,。？?\n]+)",
        r"(?:不支持|不兼容|不适配)\s*([^，,。？?\n]+)",
        r"\b(?:without|no)\s+([^,?.\n]+?)\s+(?:requirement|requirements|dependency|dependencies|support|compatibility)\b",
        r"\b(?:not compatible with|does not support|doesn't support)\s+([^,?.\n]+?)(?=\s+(?:but|and)\b|[,?.\n]|$)",
        r"\b(?:but\s+)?not\s+([^,?.\n]+?)\s+(?:compatible|compatibility|supported|support)\b",
        r"\b(?:but\s+)?(?:without|no)\s+([^,?.\n]+?)\s+(?:compatibility|support)\b",
        r"\b(?:but\s+)?not\s+([^,?.\n]+?)\s+(?:tag|tags)\b",
        r"\bbut\s+not\s+([^,?.\n]+?)(?=\s+(?:and|but)\b|[,?.\n]|$)",
        r"\bexcept\s+([^,?.\n]+?)(?=\s+(?:and|but)\b|[,?.\n]|$)",
        r"(?:不要|排除|不看|别看|不要带|不带|不含)\s*([^，,。？?\n]+)",
        r"(?:不是|并非|非)\s*([^，,。？?\n]+)",
        r"\b(?:without|exclude|excluding|no)\s+([^,?.\n]+)",
    ]:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            phrase = clean_excluded_phrase(match.group(1))
            if phrase:
                phrases.append(phrase)
    keywords: list[str] = []
    for phrase in phrases:
        expanded = expand_excluded_phrase_keywords(phrase)
        if expanded:
            keywords = _merge_unique(keywords, expanded)
        else:
            semantic = semantic_query(phrase)
            keywords = _merge_unique(keywords, [*semantic.base_keywords, *semantic.category_aliases])
    keywords = [
        keyword
        for keyword in keywords
        if alias_key(keyword) not in {alias_key(value) for value in ["成人", "adult", "nsfw", "r18"]}
    ]
    return {"excluded_keywords": keywords[:10]} if keywords else {}


def query_without_adult_markers(query: str) -> str:
    cleaned = str(query or "")
    patterns = [
        r"\b(?:no|without|exclude|excluding)\s+(?:nsfw|adult|r18|18\+)\b",
        r"\b(?:non[-\s]?adult|sfw|safe[-\s]?for[-\s]?work|nsfw|adult|r18|18\+)\b",
        r"(?:不要|排除|不含|非|不是)\s*(?:成人内容|成人|R18|NSFW)",
        r"(?:成人内容|成人|R18|NSFW)",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def clean_excluded_phrase(value: str) -> str:
    phrase = re.split(
        r"(?:\s+的\b|的|但|但是|不过|\s+(?:but|and)\b|只要|保持|同类|相关|类似|(?:\s+)?(?:mod|mods|模组|tag|tags|标签|compatible|compatibility|supported|support|requirement|requirements|dependency|dependencies)\b)",
        str(value or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return re.sub(r"\s+", " ", phrase).strip(" .:-_")


def match_has_negative_prefix(text: str, start: int) -> bool:
    window = text[max(0, start - 18) : start].lower()
    return any(
        marker in window
        for marker in [
            "不",
            "无",
            "没有",
            "不要",
            "无需",
            "without",
            " no ",
            "not ",
            "does not ",
            "doesn't ",
        ]
    )


def clean_author_value(value: str) -> str:
    cleaned = re.split(
        r"(?:\s+的\b|的|\s+(?:with|without|not|no|from|by)\b|(?:\s+)?(?:mod|mods|模组|作品|资源|标签|tag|tags|thumbnail|preview|image|images|screenshot|screenshots)\b|[，,。？?]|$)",
        str(value or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-_")
    filler_keys = {
        "mod",
        "mods",
        "author",
        "creator",
        "modder",
        "by",
        "作者",
        "创作者",
    }
    return "" if alias_key(cleaned) in {alias_key(item) for item in filler_keys} else cleaned


def clean_exact_title(value: str) -> str:
    cleaned = re.split(
        r"(?:\s+的\b|的|\s+(?:with|without|by|from)\b|(?:\s+)?(?:mod|mods|模组|详情|信息|介绍|版本|标签|tag|tags|thumbnail|preview|image|images|screenshot|screenshots)\b|[，,。？?]|$)",
        str(value or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-_\"'“”")
    blocked = {alias_key(value) for value in ["mod", "mods", "模组", "title", "name", "called", "named"]}
    return "" if alias_key(cleaned) in blocked else cleaned


def clean_version_value(value: str) -> str:
    cleaned = re.sub(r"\s+", "", str(value or "").strip()).strip(" .:-_\"'“”")
    return cleaned if re.fullmatch(r"[0-9]+(?:\.[0-9A-Za-z]+){0,4}(?:[-_][0-9A-Za-z]+)?", cleaned) else ""


def version_is_runtime_context(text: str, start: int) -> bool:
    window = text[max(0, start - 24) : start].lower()
    return bool(re.search(r"(?:game|runtime|skyrim|ae|se)\s*$", window))


def split_requirement_terms(value: str) -> list[str]:
    cleaned = re.split(
        r"(?:\s+的\b|的|\s+(?:but\s+without|but\s+not|without|not|no|except|excluding)\b|(?:\s+)?(?:mod|mods|模组|补丁|插件)\b|[，,。？?\n]|$)",
        str(value or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    parts = re.split(r"(?:/|、|\s+and\s+|\s+or\s+|\s+和\s+|\s+与\s+)", cleaned, flags=re.IGNORECASE)
    blocked = {
        alias_key(value)
        for value in [
            "mod",
            "mods",
            "requirement",
            "requirements",
            "dependency",
            "dependencies",
            "前置",
            "依赖",
            "需要",
            "要求",
        ]
    }
    terms: list[str] = []
    for part in parts:
        term = re.sub(r"\s+", " ", part).strip(" .:-_")
        if term and alias_key(term) not in blocked:
            terms.extend(expand_requirement_term(term))
    return terms


def expand_requirement_term(term: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(term or "").strip())
    key = alias_key(normalized)
    if not key:
        return []
    if key in {"scriptextender", "skyrimscriptextender"}:
        return ["SKSE"]
    return [normalized]


def expand_excluded_phrase_keywords(phrase: str) -> list[str]:
    key = alias_key(phrase)
    if key in {"scriptextender", "skyrimscriptextender"}:
        return ["skse"]
    return []


def split_compatibility_terms(value: str) -> list[str]:
    cleaned = re.split(
        r"(?:\s+的\b|的|\s+(?:but\s+without|but\s+not|without|not|no|except|excluding)\b|(?:\s+)?(?:mod|mods|模组|版本|补丁|插件)\b|[，,。？?\n]|$)",
        str(value or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    parts = re.split(r"(?:/|、|\s+and\s+|\s+or\s+|\s+和\s+|\s+与\s+)", cleaned, flags=re.IGNORECASE)
    blocked = {
        alias_key(value)
        for value in ["compatible", "compatibility", "support", "supports", "for", "兼容", "支持", "适配"]
    }
    terms: list[str] = []
    for part in parts:
        term = re.sub(r"\s+", " ", part).strip(" .:-_")
        if term and alias_key(term) not in blocked:
            terms.extend(expand_compatibility_term(term))
    return terms


def expand_compatibility_term(term: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(term or "").strip())
    if not normalized:
        return []
    versions = re.findall(r"\b[0-9]+(?:\.[0-9A-Za-z]+){1,4}(?:[-_][0-9A-Za-z]+)?\b", normalized)
    terms: list[str] = []
    lowered = normalized.lower()
    if re.search(r"\b(?:anniversary edition|ae)\b", lowered):
        terms.append("AE")
    elif re.search(r"\b(?:special edition|se)\b", lowered):
        terms.append("SE")
    elif re.search(r"\bvr\b", lowered):
        terms.append("VR")
    if versions:
        terms.extend(versions)
        if terms:
            return _merge_unique([], terms)
    cleaned = re.sub(
        r"\b(?:runtime|game\s+version|game|version|build|builds|edition)\b",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-_")
    return [cleaned] if cleaned else []

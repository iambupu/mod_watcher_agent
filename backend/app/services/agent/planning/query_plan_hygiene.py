import re
from typing import Any

from app.services.agent.list_utils import unique_text
from app.services.agent.planning.query_plan_contract import LOOSE_TERM_FIELDS

_CATEGORY_GLUE_TOKENS = {"and", "or", "of", "the", "for", "to", "with"}
_CATEGORY_TITLE_INDICATOR_TOKENS = {
    "compatible",
    "compatibility",
    "conversion",
    "converted",
    "installer",
    "optional",
    "over",
    "part",
    "replacer",
    "standalone",
    "stand",
    "version",
    "wear",
}
_CATEGORY_TAXONOMY_SEPARATORS = (",", "&", "/", "\\", "|", ":")
_GENERIC_EXACT_TITLE_KEYS = {
    "adult",
    "adultclothing",
    "adultoutfit",
    "body",
    "bodypreset",
    "clothing",
    "female",
    "femaleclothing",
    "femaleoutfit",
    "girl",
    "girlclothing",
    "girloutfit",
    "mod",
    "mods",
    "nsfw",
    "nsfwclothing",
    "nsfwoutfit",
    "outfit",
    "outfits",
    "preset",
    "r18",
    "r18clothing",
    "r18femaleclothing",
    "r18femaleoutfit",
    "r18outfit",
    "skyrim",
    "skyrimspecialedition",
    "women",
    "womenclothing",
    "womenoutfit",
    "天际",
    "女性",
    "女性服装",
    "女性衣服",
    "成人",
    "成人服装",
    "服装",
    "模组",
    "衣服",
}
_GENERIC_EXACT_TITLE_TOKENS = {
    "adult",
    "body",
    "clothing",
    "female",
    "girl",
    "mod",
    "mods",
    "nsfw",
    "outfit",
    "outfits",
    "preset",
    "r18",
    "skyrim",
    "skyrimspecialedition",
    "women",
}
_EXACT_TITLE_QUERY_MARKERS = {"只看", "仅看", "筛选", "推荐", "哪些", "有没有", "找", "查"}
def sanitize_category_slot_options(values: list[object]) -> list[str]:
    kept: list[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if looks_like_category_value(text):
            kept.append(text)
    return unique_text(kept, limit=32)


def sanitize_query_plan_fields(plan: dict[str, Any], *, query: str = "") -> dict[str, Any]:
    sanitized = dict(plan)
    if isinstance(sanitized.get("categories"), list):
        sanitized["categories"] = sanitize_category_slot_options(sanitized["categories"])
    if sanitized.get("exact_title") is not None and _looks_like_generic_exact_title(sanitized.get("exact_title")):
        sanitized.pop("exact_title", None)
    for field in LOOSE_TERM_FIELDS:
        if isinstance(sanitized.get(field), list):
            sanitized[field] = _sanitize_loose_terms(sanitized[field], query=query)
    return sanitized


def looks_like_category_value(value: object) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text or len(text) > 80:
        return False
    if _looks_like_transport_or_blob(text):
        return False
    tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", text.lower())
    if not tokens:
        return False
    meaningful = [token for token in tokens if token not in _CATEGORY_GLUE_TOKENS]
    if not meaningful:
        return False
    if len(meaningful) > 8:
        return False
    return not _looks_like_mod_title_category(text, meaningful)


def _sanitize_loose_terms(values: list[object], *, query: str) -> list[str]:
    query_lower = str(query or "").lower()
    kept: list[str] = []
    for item in values:
        value = re.sub(r"\s+", " ", str(item or "").strip())
        if not value:
            continue
        if _looks_like_transport_or_blob(value):
            continue
        if _looks_like_accidental_title_or_sentence(value, query_lower=query_lower):
            continue
        kept.append(value)
    return unique_text(kept, limit=32)


def _looks_like_transport_or_blob(value: str) -> bool:
    lowered = value.lower()
    return bool(
        lowered.startswith(("http://", "https://", "www."))
        or "\n" in value
        or "\r" in value
        or _looks_like_serialized_blob(value)
    )


def _looks_like_serialized_blob(value: str) -> bool:
    stripped = value.strip()
    if len(stripped) > 24 and (
        (stripped.startswith("{") and stripped.endswith("}"))
        or (stripped.startswith("[") and stripped.endswith("]"))
    ):
        return True
    if re.search(r"</?[a-z][^>]{0,120}>", stripped, flags=re.IGNORECASE):
        return True
    bracket_count = sum(stripped.count(char) for char in "{}[]<>")
    return len(stripped) > 120 and bracket_count >= 4


def _looks_like_mod_title_category(text: str, meaningful_tokens: list[str]) -> bool:
    lowered = text.lower()
    if _looks_like_title_dash_category(text, meaningful_tokens):
        return True
    if re.search(r"\b\d+(?:\.\d+)*\b|\b\d+k\b|\b(?:3ba|bhunp|cbbe|uunp|ube|skse|ae|se)\b", lowered):
        return True
    if re.search(r"[()]", text):
        return True
    if "'" in text and len(meaningful_tokens) >= 3:
        return True
    has_taxonomy_separator = any(separator in text for separator in _CATEGORY_TAXONOMY_SEPARATORS)
    if has_taxonomy_separator:
        return False
    indicator_hits = set(meaningful_tokens).intersection(_CATEGORY_TITLE_INDICATOR_TOKENS)
    return bool(indicator_hits and len(meaningful_tokens) >= 4)


def _looks_like_title_dash_category(text: str, meaningful_tokens: list[str]) -> bool:
    if not re.search(r"\s[-–—]\s", text):
        return False
    parts = [part.strip() for part in re.split(r"\s[-–—]\s", text) if part.strip()]
    if len(parts) < 2:
        return False
    if _looks_like_taxonomy_dash_category(parts):
        return False
    if any(re.search(r"[a-z][A-Z]", part) for part in parts):
        return True
    if any(re.search(r"[()'\"]|\b\d+(?:\.\d+)*\b", part) for part in parts):
        return True
    indicator_hits = set(meaningful_tokens).intersection(_CATEGORY_TITLE_INDICATOR_TOKENS)
    return bool(indicator_hits and len(meaningful_tokens) >= 3)


def _looks_like_taxonomy_dash_category(parts: list[str]) -> bool:
    if len(parts) > 3:
        return False
    for part in parts:
        if re.search(r"[a-z][A-Z]", part):
            return False
        if re.search(r"[()'\"]|\b\d+(?:\.\d+)*\b", part):
            return False
        tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", part.lower())
        meaningful = [token for token in tokens if token not in _CATEGORY_GLUE_TOKENS]
        if not meaningful or len(meaningful) > 3:
            return False
    return True


def _looks_like_generic_exact_title(value: object) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return False
    lowered = text.lower()
    key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", lowered)
    if key in _GENERIC_EXACT_TITLE_KEYS:
        return True
    if any(marker in text for marker in _EXACT_TITLE_QUERY_MARKERS):
        return True
    tokens = re.findall(r"[a-z0-9]+", lowered)
    return bool(tokens and all(token in _GENERIC_EXACT_TITLE_TOKENS for token in tokens))


def _looks_like_accidental_title_or_sentence(value: str, *, query_lower: str) -> bool:
    lowered = value.lower()
    if lowered and lowered in query_lower:
        return False
    tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", lowered)
    if len(value) > 96:
        return True
    return len(tokens) > 12

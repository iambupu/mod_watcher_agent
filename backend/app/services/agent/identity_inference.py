import re
from urllib.parse import urlparse

from app.services.agent.semantic_search import strip_scope
from app.services.agent.slot_aliases import SOURCE_HOST_ALIASES, source_aliases_by_source
from app.services.source_identity import canonical_external_id


def infer_identity_constraints(query: str) -> dict[str, object]:
    """从来源 URL 或站点资源 ID 中推断强身份过滤条件。"""
    text = strip_scope(query)
    url = first_source_url(text)
    if url:
        source = source_from_url(url)
        constraints: dict[str, object] = {"source_url": url}
        if source:
            constraints["sources"] = [source]
            external_id = canonical_external_id(source, "", url)
            if external_id:
                constraints["external_id"] = external_id
        return constraints

    lower_text = text.lower()
    for source, aliases in source_aliases_by_source().items():
        alias_pattern = "|".join(re.escape(alias) for alias in aliases)
        patterns = [
            rf"\b(?:{alias_pattern})\s+(?:mod\s*)?(?:id|file|resource)?\s*#?\s*(\d{{2,12}})\b",
            rf"\b(?:{alias_pattern})\b[^,\n?.]{{0,120}}\b(?:mod\s*)?(?:id|file|resource)\s*#?\s*(\d{{2,12}})\b",
            rf"\b(?:{alias_pattern})\s*#\s*(\d{{2,12}})\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, lower_text, flags=re.IGNORECASE)
            if match:
                return {"sources": [source], "external_id": match.group(1)}
    return {}


def first_source_url(text: str) -> str | None:
    pattern = r"(?:https?://|www\.)?(?:nexusmods\.com|loverslab\.com)/[^\s\"'<>，。？]+"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    url = match.group(0).rstrip(").,;:!?，。？")
    if not url.lower().startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def source_from_url(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    for source, hosts in SOURCE_HOST_ALIASES.items():
        if host in hosts:
            return source
    return None

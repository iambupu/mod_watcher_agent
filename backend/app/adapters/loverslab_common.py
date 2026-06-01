from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from app.models.mod_item import ModItem
from app.utils.boolean import parse_bool
from app.utils.time import parse_utc_datetime


def is_allowed_loverslab_url(url: str, allowed_hosts: set[str]) -> bool:
    """判断内部条件是否成立。"""
    host = (urlsplit(url).hostname or "").lower()
    return host in allowed_hosts


def validate_loverslab_url(url: str, *, kind: str, allowed_hosts: set[str]) -> str:
    """校验内部输入是否符合业务约束。"""
    normalized = (url or "").strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"LoversLab {kind} URL must be an absolute http(s) URL")
    if not is_allowed_loverslab_url(normalized, allowed_hosts):
        raise ValueError(f"LoversLab {kind} URL host is not allowed: {normalized}")
    return normalized


def parse_loverslab_updated_at(value: Any) -> datetime | None:
    """解析输入内容并返回结构化结果。"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    parsed = parse_utc_datetime(text)
    if parsed is not None:
        return parsed

    for fmt in ("%b %d, %Y %H:%M", "%b %d, %Y", "%B %d, %Y %H:%M", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue

    return None


def loverslab_mod_item_from_raw(raw_item: dict) -> ModItem:
    """处理当前模块的业务逻辑并返回结果。"""
    return ModItem(
        source_id=raw_item.get("external_id", ""),
        source=raw_item.get("source", "loverslab"),
        name=raw_item.get("title", ""),
        game=raw_item.get("game", ""),
        url=raw_item.get("url", ""),
        summary=raw_item.get("original_summary") or "",
        author=raw_item.get("author") or "",
        downloads=raw_item.get("downloads") or 0,
        endorsements=raw_item.get("endorsements") or 0,
        likes=raw_item.get("likes") or 0,
        categories=raw_item.get("categories", []),
        tags=raw_item.get("tags", []),
        thumbnail_url=raw_item.get("thumbnail_url") or "",
        updated_at=parse_loverslab_updated_at(raw_item.get("updated_at_remote")),
        is_adult=parse_bool(raw_item.get("adult_content")),
        raw=raw_item,
    )

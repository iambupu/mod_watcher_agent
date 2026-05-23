from datetime import UTC, datetime
from typing import Any

from app.models.mod_item import ModItem


def parse_loverslab_updated_at(value: Any) -> datetime | None:
    """解析输入内容并返回结构化结果。"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    try:
        iso = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(iso)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        pass

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
        is_adult=raw_item.get("adult_content", False),
        raw=raw_item,
    )

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlmodel import Session

from app.models.mod import Mod
from app.services.agent.semantic_search import strip_scope, text_score
from app.services.loverslab.constants import LOVERSLAB_HOSTS
from app.services.source_identity import canonical_external_id, find_existing_mod_by_identity

REQUEST_TIMEOUT = 20.0


@dataclass
class LoversLabSearchRecord:
    title: str
    url: str
    summary: str | None
    category: str
    thumbnail_url: str | None
    raw: dict[str, Any]


def clean_loverslab_query(query: str) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    query = strip_scope(query)
    query = re.sub(r"\bsite\s*:\s*\S+", "", query, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", query).strip()


def is_loverslab_url(url: str) -> bool:
    """判断条件是否成立。"""
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "").lower() in LOVERSLAB_HOSTS


def loverslab_external_id(url: str, *, game: str | None = None) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    return canonical_external_id(
        "loverslab",
        hashlib.sha256(url.encode("utf-8")).hexdigest()[:32],
        url,
        game=game,
    )


def clean_loverslab_title(title: str) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    return re.sub(r"\s*-\s*LoversLab\s*$", "", title, flags=re.IGNORECASE).strip()


def score_loverslab_mod(query: str, mod: Mod) -> int:
    """处理当前模块的业务逻辑并返回结果。"""
    return text_score(query, [mod.title, mod.game, mod.original_summary], [mod.category] if mod.category else None)


def upsert_loverslab_search_records(
    session: Session,
    records: list[LoversLabSearchRecord],
    *,
    game: str | None,
    adult_content: bool | None,
) -> list[Mod]:
    """处理当前模块的业务逻辑并返回结果。"""
    now = datetime.now(UTC).isoformat()
    mods: list[Mod] = []
    seen_urls: set[str] = set()
    for record in records:
        if record.url in seen_urls:
            continue
        seen_urls.add(record.url)

        title = clean_loverslab_title(record.title)
        if not title:
            continue

        external_id = loverslab_external_id(record.url, game=game)
        existing = find_existing_mod_by_identity(session, "loverslab", external_id, record.url, game=game)
        fields: dict[str, Any] = {
            "game": game,
            "game_domain": None,
            "title": title,
            "url": record.url,
            "author": None,
            "category": record.category,
            "tags_json": "[]",
            "original_summary": record.summary,
            "version": None,
            "created_at_remote": None,
            "updated_at_remote": None,
            "published_at_remote": None,
            "downloads": None,
            "unique_downloads": None,
            "endorsements": None,
            "views": None,
            "likes": None,
            "adult_content": adult_content,
            "thumbnail_url": record.thumbnail_url,
            "raw_json": json.dumps(record.raw, ensure_ascii=False),
        }
        if existing:
            for key, value in fields.items():
                if value is not None:
                    setattr(existing, key, value)
            existing.external_id = external_id
            existing.last_seen_at = now
            session.add(existing)
            mods.append(existing)
            continue

        mod = Mod(
            source="loverslab",
            external_id=external_id,
            first_seen_at=now,
            last_seen_at=now,
            **fields,
        )
        session.add(mod)
        session.flush()
        mods.append(mod)

    session.commit()
    for mod in mods:
        session.refresh(mod)
    return mods


def score_and_sort_loverslab_mods(
    mods: list[Mod],
    *,
    query: str,
    limit: int,
) -> list[tuple[int, Mod]]:
    """处理当前模块的业务逻辑并返回结果。"""
    scored = [(max(score_loverslab_mod(query, mod), 1), mod) for mod in mods if mod.id is not None and not mod.ignored]
    scored.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
    return scored[: max(1, min(20, limit))]

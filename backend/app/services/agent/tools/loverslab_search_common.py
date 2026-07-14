import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlmodel import Session

from app.models.mod import Mod
from app.services.agent.search_types import SearchResult
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
    """清理前端 scope 和 site: 片段，得到适合搜索引擎/站内检索的查询文本。"""
    query = strip_scope(query)
    query = re.sub(r"\bsite\s*:\s*\S+", "", query, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", query).strip()


def is_loverslab_url(url: str) -> bool:
    """只接受 LoversLab 官方域名，避免把普通外链误当成可物化结果。"""
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "").lower() in LOVERSLAB_HOSTS


def loverslab_external_id(url: str, *, game: str | None = None) -> str:
    """LoversLab 搜索结果缺少稳定 API id，因此用规范化 URL 哈希作为外部身份。"""
    return canonical_external_id(
        "loverslab",
        hashlib.sha256(url.encode("utf-8")).hexdigest()[:32],
        url,
        game=game,
    )


def clean_loverslab_title(title: str) -> str:
    """去掉搜索结果标题尾部的站点名，保留用户可识别的 Mod 标题。"""
    return re.sub(r"\s*-\s*LoversLab\s*$", "", title, flags=re.IGNORECASE).strip()


def score_loverslab_mod(query: str, mod: Mod) -> int:
    """按标题、游戏、摘要和分类给 LoversLab 候选做轻量相关性评分。"""
    return text_score(query, [mod.title, mod.game, mod.original_summary], [mod.category] if mod.category else None)


def upsert_loverslab_search_records(
    session: Session,
    records: list[LoversLabSearchRecord],
    *,
    game: str | None,
    adult_content: bool | None,
) -> list[Mod]:
    """将搜索记录物化为本地 Mod，并在同一批结果内按 URL 去重。"""
    now = datetime.now(UTC).isoformat()
    mods: list[Mod] = []
    seen_urls: set[str] = set()
    for record in records:
        # Google/页面抓取可能返回同一文件的多个片段，入库前先按 URL 去重。
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
            # 搜索记录通常没有完整元数据，None 不覆盖旧值，避免擦掉已有版本/统计字段。
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
    """过滤忽略项后按相关性排序，返回给上层统一物化为 SearchResult。"""
    scored = [(max(score_loverslab_mod(query, mod), 1), mod) for mod in mods if mod.id is not None and not mod.ignored]
    scored.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
    return scored[: max(1, min(20, limit))]


def loverslab_search_results(
    mods: list[Mod],
    *,
    query: str,
    limit: int,
    tool_name: str,
) -> list[SearchResult]:
    """Score LoversLab records and materialize the shared search result shape."""
    scored = score_and_sort_loverslab_mods(mods, query=query, limit=limit)
    return [SearchResult(score=score, mod=mod, tool_name=tool_name) for score, mod in scored]

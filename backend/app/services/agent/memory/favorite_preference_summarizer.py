from collections import Counter
from typing import Any

from sqlmodel import Session, select

from app.models.favorite import Favorite
from app.models.mod import Mod

ADULT_COUNT_THRESHOLD = 5
ADULT_RATIO_THRESHOLD = 0.35
ADULT_RATIO_MIN_SAMPLE = 8


def summarize_favorite_preferences(session: Session) -> dict[str, Any]:
    rows = session.exec(select(Mod).join(Favorite, Favorite.mod_id == Mod.id)).all()
    total = len(rows)
    adult_count = sum(1 for mod in rows if mod.adult_content is True)
    adult_ratio = adult_count / total if total else 0.0
    top_games = _top_values(mod.game for mod in rows)
    top_sources = _top_values(mod.source for mod in rows)
    top_categories = _top_values(mod.category for mod in rows)
    adult_allowed = adult_count >= ADULT_COUNT_THRESHOLD or (
        total >= ADULT_RATIO_MIN_SAMPLE and adult_ratio >= ADULT_RATIO_THRESHOLD
    )
    return {
        "favorite_count": total,
        "top_games": top_games,
        "top_sources": top_sources,
        "top_categories": top_categories,
        "adult_content_count": adult_count,
        "adult_content_ratio": round(adult_ratio, 4),
        "adult_content_allowed": adult_allowed,
        "summary": _summary_text(top_games, top_categories, top_sources, adult_allowed),
    }


def _top_values(values) -> list[str]:
    counter = Counter(str(value).strip() for value in values if str(value or "").strip())
    return [value for value, _count in counter.most_common(5)]


def _summary_text(
    top_games: list[str],
    top_categories: list[str],
    top_sources: list[str],
    adult_allowed: bool,
) -> str:
    parts = []
    if top_games:
        parts.append(f"用户收藏偏向 {', '.join(top_games[:3])}")
    if top_categories:
        parts.append(f"常见分类为 {', '.join(top_categories[:3])}")
    if top_sources:
        parts.append(f"常见来源为 {', '.join(top_sources[:3])}")
    parts.append("收藏中成人内容偏好较明显" if adult_allowed else "收藏中成人内容偏好不明显")
    return "；".join(parts) + "。"

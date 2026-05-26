from dataclasses import dataclass
from typing import Any

from app.models.mod import Mod


@dataclass(frozen=True)
class SearchPlan:
    keywords: list[str]
    excluded_keywords: list[str]
    games: list[str]
    game_domains: list[str]
    categories: list[str]
    tags: list[str]
    summary_languages: list[str]
    excluded_summary_languages: list[str]
    requirement_terms: list[str]
    compatibility_terms: list[str]
    sources: list[str]
    author: str | None
    exact_title: str | None
    version: str | None
    external_id: str | None
    source_url: str | None
    has_thumbnail: bool | None
    adult_content: bool | None
    sort_field: str
    sort_order: str
    limit: int
    min_downloads: int | None = None
    min_endorsements: int | None = None
    min_views: int | None = None
    min_likes: int | None = None
    updated_since_days: int | None = None
    updated_after: str | None = None
    updated_before: str | None = None
    published_after: str | None = None
    published_before: str | None = None
    created_after: str | None = None
    created_before: str | None = None
    category_match_mode: str | None = None

    @classmethod
    def from_query_plan(cls, plan: dict[str, Any]) -> "SearchPlan":
        try:
            limit = int(plan.get("limit") or 8)
        except (TypeError, ValueError):
            limit = 8
        adult_content = plan.get("adult_content")
        return cls(
            keywords=_string_list(plan.get("keywords")),
            excluded_keywords=_string_list(plan.get("excluded_keywords")),
            games=_string_list(plan.get("games")),
            game_domains=_string_list(plan.get("game_domains")),
            categories=_string_list(plan.get("categories")),
            tags=_string_list(plan.get("tags")),
            summary_languages=_string_list(plan.get("summary_languages")),
            excluded_summary_languages=_string_list(plan.get("excluded_summary_languages")),
            requirement_terms=_string_list(plan.get("requirement_terms")),
            compatibility_terms=_string_list(plan.get("compatibility_terms")),
            sources=_string_list(plan.get("sources")),
            author=_optional_string(plan.get("author")),
            exact_title=_optional_string(plan.get("exact_title")),
            version=_optional_string(plan.get("version")),
            external_id=_optional_string(plan.get("external_id")),
            source_url=_optional_string(plan.get("source_url")),
            has_thumbnail=plan.get("has_thumbnail") if isinstance(plan.get("has_thumbnail"), bool) else None,
            adult_content=adult_content if isinstance(adult_content, bool) else None,
            sort_field=str(plan.get("sort_field") or "relevance"),
            sort_order="asc" if str(plan.get("sort_order") or "").lower() == "asc" else "desc",
            limit=max(1, min(20, limit)),
            min_downloads=_optional_int(plan.get("min_downloads")),
            min_endorsements=_optional_int(plan.get("min_endorsements")),
            min_views=_optional_int(plan.get("min_views")),
            min_likes=_optional_int(plan.get("min_likes")),
            updated_since_days=_optional_positive_int(plan.get("updated_since_days")),
            updated_after=_optional_string(plan.get("updated_after")),
            updated_before=_optional_string(plan.get("updated_before")),
            published_after=_optional_string(plan.get("published_after")),
            published_before=_optional_string(plan.get("published_before")),
            created_after=_optional_string(plan.get("created_after")),
            created_before=_optional_string(plan.get("created_before")),
            category_match_mode=str(plan.get("category_match_mode") or "") or None,
        )

    def to_query_plan(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "keywords": self.keywords,
            "excluded_keywords": self.excluded_keywords,
            "games": self.games,
            "game_domains": self.game_domains,
            "categories": self.categories,
            "tags": self.tags,
            "summary_languages": self.summary_languages,
            "excluded_summary_languages": self.excluded_summary_languages,
            "requirement_terms": self.requirement_terms,
            "compatibility_terms": self.compatibility_terms,
            "sources": self.sources,
            "author": self.author,
            "exact_title": self.exact_title,
            "version": self.version,
            "external_id": self.external_id,
            "source_url": self.source_url,
            "has_thumbnail": self.has_thumbnail,
            "adult_content": self.adult_content,
            "sort_field": self.sort_field,
            "sort_order": self.sort_order,
            "limit": self.limit,
            "min_downloads": self.min_downloads,
            "min_endorsements": self.min_endorsements,
            "min_views": self.min_views,
            "min_likes": self.min_likes,
            "updated_since_days": self.updated_since_days,
            "updated_after": self.updated_after,
            "updated_before": self.updated_before,
            "published_after": self.published_after,
            "published_before": self.published_before,
            "created_after": self.created_after,
            "created_before": self.created_before,
        }
        if self.category_match_mode:
            data["category_match_mode"] = self.category_match_mode
        return data


@dataclass(frozen=True)
class SearchResult:
    score: int
    mod: Mod
    tool_name: str
    score_breakdown: dict[str, int] | None = None
    rank_reason: str | None = None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    else:
        values = list(value) if isinstance(value, list | tuple | set) else []
    return [str(item).strip() for item in values if str(item).strip()]


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    try:
        parsed = int(str(value or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _optional_positive_int(value: Any) -> int | None:
    parsed = _optional_int(value)
    if parsed is None:
        return None
    return max(1, min(365, parsed))

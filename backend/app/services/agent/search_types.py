from dataclasses import dataclass
from typing import Any

from app.models.mod import Mod


@dataclass(frozen=True)
class SearchPlan:
    keywords: list[str]
    games: list[str]
    game_domains: list[str]
    categories: list[str]
    sources: list[str]
    adult_content: bool | None
    sort_field: str
    sort_order: str
    limit: int
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
            games=_string_list(plan.get("games")),
            game_domains=_string_list(plan.get("game_domains")),
            categories=_string_list(plan.get("categories")),
            sources=_string_list(plan.get("sources")),
            adult_content=adult_content if isinstance(adult_content, bool) else None,
            sort_field=str(plan.get("sort_field") or "relevance"),
            sort_order="asc" if str(plan.get("sort_order") or "").lower() == "asc" else "desc",
            limit=max(1, min(20, limit)),
            category_match_mode=str(plan.get("category_match_mode") or "") or None,
        )

    def to_query_plan(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "keywords": self.keywords,
            "games": self.games,
            "game_domains": self.game_domains,
            "categories": self.categories,
            "sources": self.sources,
            "adult_content": self.adult_content,
            "sort_field": self.sort_field,
            "sort_order": self.sort_order,
            "limit": self.limit,
        }
        if self.category_match_mode:
            data["category_match_mode"] = self.category_match_mode
        return data


@dataclass(frozen=True)
class SearchResult:
    score: int
    mod: Mod
    tool_name: str


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    else:
        values = list(value) if isinstance(value, list | tuple | set) else []
    return [str(item).strip() for item in values if str(item).strip()]

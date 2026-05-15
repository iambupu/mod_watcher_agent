import json
from datetime import datetime, timezone
from typing import Any, Callable

from sqlmodel import Session, and_, or_, select

from app.models.mod import Mod
from app.schemas.watch_rule import CommonRuleFilters


class FilterService:
    """Service for applying watch rule filters to discovered mods.

    Uses two-phase filtering:
      1. Deterministic filters (always run)
      2. LLM-assisted filter (only if llmFilter.enabled=true)
    """

    def __init__(self, llm_client: Callable[..., list[dict]] | None = None):
        self.llm_client = llm_client

    def apply_filters(
        self, rule: Any, mods: list[dict], db_session: Session
    ) -> list[dict]:
        filters = self._parse_filters(rule)

        passed = [
            m for m in mods if self._passes_deterministic(m, filters)
        ]

        if filters.llmFilter.enabled and self.llm_client:
            passed = self._apply_llm_filter(passed, filters)

        return self._deduplicate(passed, db_session)

    def _parse_filters(self, rule: Any) -> CommonRuleFilters:
        if hasattr(rule, "filters_json"):
            return CommonRuleFilters.model_validate_json(rule.filters_json)
        if isinstance(rule, CommonRuleFilters):
            return rule
        raise ValueError(f"Cannot parse filters from rule type: {type(rule)}")

    def _passes_deterministic(
        self, mod: dict, filters: CommonRuleFilters
    ) -> bool:
        if not self._filter_by_keywords(
            mod, filters.includeKeywords, filters.excludeKeywords
        ):
            return False
        if not self._filter_by_stats(
            mod,
            filters.minDownloads,
            filters.minEndorsements,
            filters.minLikes,
        ):
            return False
        if not self._filter_by_updated_within(mod, filters.updatedWithinDays):
            return False
        if not self._filter_by_adult(mod, filters.adultPolicy):
            return False
        if not self._filter_by_missing_metrics(mod, filters):
            return False
        return True

    def _filter_by_keywords(
        self,
        mod: dict,
        include_keywords: list[str],
        exclude_keywords: list[str],
    ) -> bool:
        text = (mod.get("title") or "") + " " + (mod.get("original_summary") or "")
        text = text.lower()

        if include_keywords:
            if not any(kw.lower() in text for kw in include_keywords):
                return False

        if exclude_keywords:
            if any(kw.lower() in text for kw in exclude_keywords):
                return False

        return True

    def _filter_by_stats(
        self,
        mod: dict,
        min_downloads: int | None,
        min_endorsements: int | None,
        min_likes: int | None,
    ) -> bool:
        if min_downloads is not None and (mod.get("downloads") or 0) < min_downloads:
            return False
        if min_endorsements is not None and (mod.get("endorsements") or 0) < min_endorsements:
            return False
        if min_likes is not None and (mod.get("likes") or 0) < min_likes:
            return False
        return True

    def _filter_by_updated_within(
        self, mod: dict, updated_within_days: int | None
    ) -> bool:
        if updated_within_days is None:
            return True
        updated_str = mod.get("updated_at_remote") or mod.get("published_at_remote")
        if not updated_str:
            return True
        try:
            updated = datetime.fromisoformat(updated_str)
            age_hours = (
                datetime.now(timezone.utc) - updated
            ).total_seconds() / 3600
            return age_hours <= updated_within_days * 24
        except (ValueError, TypeError):
            return True

    def _filter_by_adult(self, mod: dict, adult_policy: str) -> bool:
        is_adult = bool(mod.get("adult_content"))

        if adult_policy == "exclude" and is_adult:
            return False

        if adult_policy == "only" and not is_adult:
            return False

        return True

    def _filter_by_missing_metrics(
        self, mod: dict, filters: CommonRuleFilters
    ) -> bool:
        if filters.missingMetricsPolicy != "reject":
            return True

        has_downloads = (mod.get("downloads") or 0) > 0
        has_endorsements = (mod.get("endorsements") or 0) > 0
        has_likes = (mod.get("likes") or 0) > 0

        if not (has_downloads or has_endorsements or has_likes):
            return False
        return True

    def _apply_llm_filter(
        self, mods: list[dict], filters: CommonRuleFilters
    ) -> list[dict]:
        if not mods:
            return []
        return self.llm_client(mods, filters.llmFilter)

    def _deduplicate(
        self, mods: list[dict], db_session: Session
    ) -> list[dict]:
        if not mods:
            return []

        pairs = list({(m["source"], m["external_id"]) for m in mods})

        existing = db_session.exec(
            select(Mod.source, Mod.external_id, Mod.ignored).where(
                or_(*[and_(Mod.source == s, Mod.external_id == eid) for s, eid in pairs])
            )
        ).all()

        existing_ids = {f"{row[0]}:{row[1]}" for row in existing}
        ignored_ids = {f"{row[0]}:{row[1]}" for row in existing if row[2]}

        return [
            m for m in mods
            if f"{m['source']}:{m['external_id']}" not in existing_ids
            and f"{m['source']}:{m['external_id']}" not in ignored_ids
        ]

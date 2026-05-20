from typing import Any


class RankingService:
    """Service for ranking and sorting discovered mods."""

    def sort_mods(self, mods: list[dict], sort_mode: str) -> list[dict]:
        """Sort mods according to the specified sort mode.

        Supported modes: updated_desc, updated_asc, published_desc, published_asc,
        downloads_desc, downloads_asc, endorsements_desc, endorsements_asc.
        """
        reverse = "_desc" in sort_mode

        if "downloads" in sort_mode:
            def key(mod: dict) -> int:
                return mod.get("downloads") or 0
        elif "endorsements" in sort_mode:
            def key(mod: dict) -> int:
                return mod.get("endorsements") or 0
        elif "published" in sort_mode:
            def key(mod: dict) -> str:
                return mod.get("published_at_remote") or mod.get("created_at_remote") or ""
        elif "updated" in sort_mode:
            def key(mod: dict) -> str:
                return mod.get("updated_at_remote") or mod.get("first_seen_at") or ""
        else:
            def key(mod: dict) -> str:
                return mod.get("first_seen_at") or ""

        return sorted(mods, key=key, reverse=reverse)

    def rank_by_popularity(self, mods: list[dict]) -> list[dict]:
        """Rank mods by download count (descending)."""
        return sorted(mods, key=lambda m: m.get("downloads") or 0, reverse=True)

    def rank_by_recency(self, mods: list[dict]) -> list[dict]:
        """Rank mods by their published/updated date (newest first)."""
        def _sort_key(mod: dict) -> str:
            return (mod.get("published_at_remote")
                    or mod.get("updated_at_remote")
                    or mod.get("created_at_remote")
                    or "")
        return sorted(mods, key=_sort_key, reverse=True)

    def rank_by_relevance(self, mods: list[dict], rule: Any) -> list[dict]:
        """Rank mods by relevance to the watch rule criteria (descending)."""
        return sorted(
            mods,
            key=lambda m: self.compute_relevance_score(m, rule),
            reverse=True,
        )

    def compute_relevance_score(self, mod: dict, rule: Any) -> float:
        """Compute a relevance score (0.0 to 1.0) for a mod against a rule.

        Components:
        - Keyword match in title (0.6 max): title contains include_keywords
        - Stats match (0.4 max): downloads/endorsements high relative to thresholds
        """
        score = 0.0

        # Keyword relevance: title matching include_keywords
        import json
        include_keywords = json.loads(getattr(rule, "include_keywords_json", "[]"))
        if include_keywords:
            title_lower = (mod.get("title") or "").lower()
            matches = sum(1 for kw in include_keywords if kw.lower() in title_lower)
            score += 0.6 * (matches / len(include_keywords))

        # Stats relevance: downloads and endorsements
        min_downloads = getattr(rule, "min_downloads", None)
        min_endorsements = getattr(rule, "min_endorsements", None)
        downloads = mod.get("downloads") or 0
        endorsements = mod.get("endorsements") or 0

        if min_downloads and min_downloads > 0:
            score += 0.2 * min(downloads / min_downloads, 1.0)
        if min_endorsements and min_endorsements > 0:
            score += 0.2 * min(endorsements / min_endorsements, 1.0)

        return round(min(score, 1.0), 4)

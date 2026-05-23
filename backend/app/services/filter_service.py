from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, and_, or_, select

from app.models.mod import Mod
from app.schemas.watch_rule import CommonRuleFilters


class FilterService:
    """Service for applying watch rule filters to discovered mods.

    Uses two-phase filtering:
      1. Deterministic filters (always run)
      2. LLM-assisted filter (only if llmFilter.enabled=true)
    """

    def __init__(self, llm_client: Callable[..., Any] | None = None):
        """初始化实例并保存运行所需的依赖。"""
        self.llm_client = llm_client

    def apply_filters(
        self, rule: Any, mods: list[dict], db_session: Session
    ) -> list[dict]:
        """处理当前模块的业务逻辑并返回结果。"""
        filters = self._parse_filters(rule)
        self.rejected_reasons: dict[str, int] = {}
        self.rejected_items: list[dict] = []
        self._pending_soft_rejection: str | None = None

        deterministic_passed: list[dict] = []
        for mod in mods:
            self._pending_soft_rejection = None
            reject_reason = self._get_deterministic_reject_reason(mod, filters)
            if reject_reason is None:
                if self._pending_soft_rejection:
                    self._record_rejection(
                        mod,
                        self._pending_soft_rejection,
                        stage="deterministic_hint",
                    )
                deterministic_passed.append(mod)
                continue
            self._record_rejection(mod, reject_reason, stage="deterministic")

        self.stats = {
            "passed_deterministic": len(deterministic_passed),
            # If LLM filter is disabled, semantic equals deterministic pass count.
            "passed_llm": len(deterministic_passed),
        }

        if filters.llmFilter.enabled and self.llm_client:
            llm_passed = self._apply_llm_filter(deterministic_passed, filters)
        else:
            llm_passed = deterministic_passed

        self.stats["passed_llm"] = len(llm_passed)
        self.preview_items_before_deduplicate = llm_passed

        deduplicated = self._deduplicate(llm_passed, db_session)
        accepted_ids = {
            f"{m.get('source', '')}:{m.get('external_id', '')}" for m in deduplicated
        }
        for mod in llm_passed:
            mod_key = f"{mod.get('source', '')}:{mod.get('external_id', '')}"
            if mod_key in accepted_ids:
                continue
            self._record_rejection(mod, "already_exists_or_ignored", stage="deduplicate")

        return deduplicated

    def _parse_filters(self, rule: Any) -> CommonRuleFilters:
        """解析原始内容并返回结构化结果。"""
        if hasattr(rule, "filters_json"):
            return CommonRuleFilters.model_validate_json(rule.filters_json)
        if isinstance(rule, CommonRuleFilters):
            return rule
        raise ValueError(f"Cannot parse filters from rule type: {type(rule)}")

    def _get_deterministic_reject_reason(
        self, mod: dict, filters: CommonRuleFilters
    ) -> str | None:
        """读取内部状态或派生结果。"""
        text = ((mod.get("title") or "") + " " + (mod.get("original_summary") or "")).lower()
        include_keywords = filters.includeKeywords or []
        exclude_keywords = filters.excludeKeywords or []
        if include_keywords and not any(kw.lower() in text for kw in include_keywords):
            return "include_keywords_mismatch"
        if exclude_keywords and any(kw.lower() in text for kw in exclude_keywords):
            return "exclude_keywords_hit"

        downloads = mod.get("downloads")
        endorsements = mod.get("endorsements")
        likes = mod.get("likes")
        if filters.minDownloads is not None and (downloads or 0) < filters.minDownloads:
            return "min_downloads_not_met"
        if filters.minEndorsements is not None and (endorsements or 0) < filters.minEndorsements:
            return "min_endorsements_not_met"
        if filters.minLikes is not None and (likes or 0) < filters.minLikes:
            return "min_likes_not_met"

        if filters.updatedWithinDays is not None:
            updated_str = mod.get("updated_at_remote") or mod.get("published_at_remote")
            if updated_str:
                try:
                    updated = datetime.fromisoformat(updated_str)
                    age_hours = (datetime.now(UTC) - updated).total_seconds() / 3600
                    if age_hours > filters.updatedWithinDays * 24:
                        return "updated_within_days_not_met"
                except (ValueError, TypeError):
                    mode = str(getattr(filters.llmFilter, "mode", "assist_only") or "assist_only")
                    if mode == "must_pass":
                        return "updated_within_days_parse_failed"
                    self._pending_soft_rejection = "updated_within_days_parse_failed"

        is_adult = bool(mod.get("adult_content"))
        if filters.adultPolicy == "exclude" and is_adult:
            return "adult_content_excluded"
        if filters.adultPolicy == "only" and not is_adult:
            return "adult_content_only_not_met"

        if filters.missingMetricsPolicy == "reject":
            has_downloads = (downloads or 0) > 0
            has_endorsements = (endorsements or 0) > 0
            has_likes = (likes or 0) > 0
            if not (has_downloads or has_endorsements or has_likes):
                return "missing_metrics_rejected"

        return None

    def _apply_llm_filter(
        self, mods: list[dict], filters: CommonRuleFilters
    ) -> list[dict]:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        if not mods:
            return []
        llm_result: Any = None
        try:
            llm_result = self.llm_client(mods, filters.llmFilter, return_details=True)
        except TypeError:
            llm_result = self.llm_client(mods, filters.llmFilter)

        if isinstance(llm_result, dict) and isinstance(llm_result.get("items"), list):
            passed = llm_result.get("items") or []
            details = llm_result.get("details") or []
            for detail in details:
                if detail.get("decision") == "reject":
                    mod = detail.get("mod") or {}
                    self._record_rejection(
                        mod,
                        "llm_rejected",
                        stage="llm",
                        llm_feedback=detail.get("feedback") or "",
                    )
            return passed

        passed = llm_result if isinstance(llm_result, list) else []
        passed_keys = {
            f"{m.get('source', '')}:{m.get('external_id', '')}" for m in passed
        }
        for mod in mods:
            mod_key = f"{mod.get('source', '')}:{mod.get('external_id', '')}"
            if mod_key in passed_keys:
                continue
            self._record_rejection(mod, "llm_rejected", stage="llm")
        return passed

    def _deduplicate(
        self, mods: list[dict], db_session: Session
    ) -> list[dict]:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
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

    def _record_rejection(
        self,
        mod: dict,
        reason: str,
        *,
        stage: str,
        llm_feedback: str = "",
    ) -> None:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        self.rejected_reasons[reason] = self.rejected_reasons.get(reason, 0) + 1
        self.rejected_items.append(
            {
                "source": mod.get("source", ""),
                "externalId": str(mod.get("external_id", "")),
                "title": mod.get("title", ""),
                "game": mod.get("game", ""),
                "url": mod.get("url", ""),
                "reason": reason,
                "stage": stage,
                "llmFeedback": llm_feedback,
            }
        )

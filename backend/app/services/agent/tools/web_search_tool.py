import logging
from dataclasses import dataclass

from sqlmodel import Session

from app.services.agent.search_types import SearchResult
from app.services.agent.tools.loverslab_google_search_tool import (
    LoversLabGoogleSearchTool,
    loverslab_google_input_from_plan,
)
from app.services.agent.tools.loverslab_search_scrape_tool import (
    LoversLabSearchScrapeTool,
    loverslab_scrape_input_from_plan,
)
from app.services.agent.tools.nexusmods_search_tool import (
    NexusModsSearchTool,
    nexus_tool_input_from_plan,
)

logger = logging.getLogger(__name__)


@dataclass
class WebSearchOutput:
    results: list[SearchResult]
    evidence: list[dict[str, object]]


class WebSearchTool:
    """Encapsulates all online search execution and adaptation evidence."""

    name = "web_search"

    def __init__(self, session: Session):
        self.session = session

    async def run(
        self,
        *,
        query: str,
        query_plan: dict,
        evidence_id: str = "",
        conservative_mode: bool = False,
        allowed_tools: set[str] | None = None,
    ) -> WebSearchOutput:
        results: list[SearchResult] = []
        evidence: list[dict[str, object]] = []
        allowed = (
            {"nexusmods_search", "loverslab_google", "loverslab_scrape"}
            if allowed_tools is None
            else allowed_tools
        )

        nexus_input = nexus_tool_input_from_plan(self.session, query, query_plan)
        if "nexusmods_search" not in allowed:
            logger.info(
                "agent.retrieval.online tool=nexusmods_search status=skipped reason=not_planned count=0 evidence_id=%s",
                evidence_id,
            )
            self._append_evidence(
                evidence,
                stage="online_retrieval",
                tool="nexusmods_search",
                status="skipped",
                count=0,
                reason="not_planned",
                fields=["tool_plan"],
                evidence_id=evidence_id,
            )
        elif nexus_input is not None:
            nexus_tool = NexusModsSearchTool(self.session)
            nexus_results = await nexus_tool.run(nexus_input)
            status, reason = _tool_status(nexus_tool, nexus_results)
            logger.info(
                "agent.retrieval.online tool=nexusmods_search status=%s count=%s reason=%s evidence_id=%s",
                status,
                len(nexus_results),
                reason or "",
                evidence_id,
            )
            self._append_evidence(
                evidence,
                stage="online_retrieval",
                tool="nexusmods_search",
                status=status,
                count=len(nexus_results),
                reason=reason,
                fields=_query_plan_fields(query_plan),
                evidence_id=evidence_id,
            )
            results.extend(nexus_results)
        else:
            logger.info(
                "agent.retrieval.online tool=nexusmods_search status=skipped reason=source_filter count=0 evidence_id=%s",
                evidence_id,
            )
            self._append_evidence(
                evidence,
                stage="online_retrieval",
                tool="nexusmods_search",
                status="skipped",
                count=0,
                reason="source_filter",
                fields=["sources"],
                evidence_id=evidence_id,
            )

        loverslab_input = loverslab_google_input_from_plan(query, query_plan)
        if "loverslab_google" not in allowed:
            logger.info(
                "agent.retrieval.online tool=loverslab_google status=skipped reason=not_planned count=0 evidence_id=%s",
                evidence_id,
            )
            self._append_evidence(
                evidence,
                stage="online_retrieval",
                tool="loverslab_google",
                status="skipped",
                count=0,
                reason="not_planned",
                fields=["tool_plan"],
                evidence_id=evidence_id,
            )
        elif loverslab_input is not None:
            loverslab_tool = LoversLabGoogleSearchTool(self.session)
            loverslab_results = await loverslab_tool.run(loverslab_input)
            status, reason = _tool_status(loverslab_tool, loverslab_results)
            logger.info(
                "agent.retrieval.online tool=loverslab_google status=%s count=%s reason=%s evidence_id=%s",
                status,
                len(loverslab_results),
                reason or "",
                evidence_id,
            )
            self._append_evidence(
                evidence,
                stage="online_retrieval",
                tool="loverslab_google",
                status=status,
                count=len(loverslab_results),
                reason=reason,
                fields=_query_plan_fields(query_plan),
                evidence_id=evidence_id,
            )
            results.extend(loverslab_results)
            if not loverslab_results and status != "skipped":
                scrape_input = loverslab_scrape_input_from_plan(query, query_plan)
                if "loverslab_scrape" in allowed and scrape_input is not None:
                    scrape_tool = LoversLabSearchScrapeTool(self.session)
                    scrape_results = await scrape_tool.run(scrape_input)
                    status, reason = _tool_status(scrape_tool, scrape_results)
                    logger.info(
                        "agent.retrieval.online tool=loverslab_scrape status=%s count=%s reason=%s evidence_id=%s",
                        status,
                        len(scrape_results),
                        reason or "",
                        evidence_id,
                    )
                    self._append_evidence(
                        evidence,
                        stage="online_retrieval",
                        tool="loverslab_scrape",
                        status=status,
                        count=len(scrape_results),
                        reason=reason,
                        fields=_query_plan_fields(query_plan),
                        evidence_id=evidence_id,
                    )
                    results.extend(scrape_results)
                else:
                    logger.info(
                        "agent.retrieval.online tool=loverslab_scrape status=skipped reason=source_filter count=0 evidence_id=%s",
                        evidence_id,
                    )
                    self._append_evidence(
                        evidence,
                        stage="online_retrieval",
                        tool="loverslab_scrape",
                        status="skipped",
                        count=0,
                        reason="source_filter",
                        fields=["sources"],
                        evidence_id=evidence_id,
                    )
        else:
            logger.info(
                "agent.retrieval.online tool=loverslab_google status=skipped reason=source_filter count=0 evidence_id=%s",
                evidence_id,
            )
            self._append_evidence(
                evidence,
                stage="online_retrieval",
                tool="loverslab_google",
                status="skipped",
                count=0,
                reason="source_filter",
                fields=["sources"],
                evidence_id=evidence_id,
            )

        if conservative_mode and not results:
            self._append_evidence(
                evidence,
                stage="online_adaptation",
                tool="online_strategy",
                status="suggested",
                count=0,
                reason="conservative_online_zero_result_expand_sources",
                fields=["sources", "adult_content", "keywords"],
                evidence_id=evidence_id,
            )
        succeeded_tools = [
            str(item.get("tool"))
            for item in evidence
            if item.get("stage") == "online_retrieval"
            and item.get("status") == "succeeded"
            and int(item.get("count") or 0) > 0
        ]
        degraded_tools = [
            str(item.get("tool"))
            for item in evidence
            if item.get("stage") == "online_retrieval" and item.get("status") == "degraded"
        ]
        online_statuses = [
            str(item.get("status"))
            for item in evidence
            if item.get("stage") == "online_retrieval"
        ]
        adaptation_triggered = any(item.get("stage") == "online_adaptation" for item in evidence)
        if degraded_tools and not results:
            web_status = "degraded"
        elif not results and online_statuses and all(status == "skipped" for status in online_statuses):
            web_status = "skipped"
        else:
            web_status = "succeeded"
        logger.info(
            "agent.tool name=web_search status=%s results=%s evidence=%s tools=%s degraded_tools=%s adaptation=%s conservative_mode=%s evidence_id=%s",
            web_status,
            len(results),
            len(evidence),
            succeeded_tools,
            degraded_tools,
            adaptation_triggered,
            conservative_mode,
            evidence_id,
        )
        return WebSearchOutput(results=results, evidence=evidence)

    def _append_evidence(
        self,
        evidence: list[dict[str, object]],
        *,
        stage: str,
        tool: str,
        status: str,
        count: int,
        reason: str | None = None,
        fields: list[str] | None = None,
        evidence_id: str = "",
    ) -> None:
        fragment_id = f"r_web_{len(evidence) + 1}"
        item: dict[str, object] = {
            "fragment_id": fragment_id,
            "stage": stage,
            "tool": tool,
            "status": status,
            "count": count,
        }
        if evidence_id:
            item["evidence_id"] = evidence_id
        if reason:
            item["reason"] = reason
        if fields:
            item["fields"] = fields
        evidence.append(item)


def _query_plan_fields(query_plan: dict) -> list[str]:
    field_keys = [
        "keywords",
        "games",
        "game_domains",
        "sources",
        "categories",
        "tags",
        "adult_content",
        "has_thumbnail",
        "summary_languages",
        "excluded_summary_languages",
        "requirement_terms",
        "compatibility_terms",
        "author",
        "sort_field",
        "sort_order",
        "exact_title",
        "version",
        "external_id",
        "source_url",
    ]
    active: list[str] = []
    for key in field_keys:
        value = query_plan.get(key)
        if value in (None, "", []):
            continue
        active.append(key)
    return active


def _tool_status(tool: object, results: list[SearchResult] | None = None) -> tuple[str, str | None]:
    status = str(getattr(tool, "last_status", "succeeded") or "succeeded")
    reason = getattr(tool, "last_reason", None)
    if status == "not_started" and results:
        status = "succeeded"
    return status, str(reason) if reason else None

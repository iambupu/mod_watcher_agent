import logging
from dataclasses import dataclass
from typing import Any

from app.services.agent.retrievers.qdrant_retriever import QdrantRetriever
from app.services.agent.search_types import SearchResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorSearchInput:
    query: str
    filters: dict[str, Any]
    limit: int
    evidence_id: str = ""


@dataclass(frozen=True)
class VectorSearchOutput:
    results: list[SearchResult]
    evidence: list[dict[str, object]]
    degraded_reason: str | None = None


class VectorSearchTool:
    """Agent tool for optional vector retrieval with explicit degradation evidence."""

    name = "vector_search"

    def __init__(self, *, enabled: bool = False, client: Any | None = None):
        self.retriever = QdrantRetriever(enabled=enabled, client=client)

    def run(self, tool_input: VectorSearchInput) -> VectorSearchOutput:
        result = self.retriever.search(query=tool_input.query, filters=tool_input.filters, limit=tool_input.limit)
        if result.degraded_reason:
            logger.info(
                "agent.retrieval.vector status=degraded reason=%s count=0 evidence_id=%s",
                result.degraded_reason,
                tool_input.evidence_id,
            )
            logger.info(
                "agent.tool name=vector_search status=degraded reason=%s count=0 evidence_id=%s",
                result.degraded_reason,
                tool_input.evidence_id,
            )
            return VectorSearchOutput(
                results=[],
                degraded_reason=result.degraded_reason,
                evidence=[
                    {
                        "fragment_id": "r_vector_1",
                        "stage": "vector_retrieval",
                        "tool": "qdrant_vector",
                        "status": "degraded",
                        "count": 0,
                        "evidence_id": tool_input.evidence_id,
                        "reason": result.degraded_reason,
                        "fields": _query_plan_fields(tool_input.filters),
                    }
                ],
            )
        logger.info(
            "agent.retrieval.vector status=succeeded count=%s evidence_id=%s",
            len(result.results),
            tool_input.evidence_id,
        )
        logger.info(
            "agent.tool name=vector_search status=succeeded count=%s evidence_id=%s",
            len(result.results),
            tool_input.evidence_id,
        )
        return VectorSearchOutput(
            results=result.results,
            evidence=[
                    {
                        "fragment_id": "r_vector_1",
                        "stage": "vector_retrieval",
                        "tool": "qdrant_vector",
                        "status": "succeeded",
                        "count": len(result.results),
                        "evidence_id": tool_input.evidence_id,
                        "fields": _query_plan_fields(tool_input.filters),
                    }
            ],
        )


def _query_plan_fields(query_plan: dict[str, Any]) -> list[str]:
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
    return [key for key in field_keys if query_plan.get(key) not in (None, "", [])]

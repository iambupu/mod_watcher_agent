from dataclasses import dataclass
from typing import Any

from app.services.agent.search_types import SearchResult


@dataclass(frozen=True)
class QdrantSearchResult:
    results: list[SearchResult]
    degraded_reason: str | None = None


class QdrantRetriever:
    def __init__(self, *, enabled: bool = False, client: Any | None = None):
        self.enabled = enabled
        self.client = client

    def search(self, *, query: str, filters: dict[str, Any], limit: int) -> QdrantSearchResult:
        if not self.enabled:
            return QdrantSearchResult(results=[], degraded_reason="qdrant_disabled")
        if self.client is None:
            return QdrantSearchResult(results=[], degraded_reason="qdrant_unavailable")
        return QdrantSearchResult(results=[], degraded_reason="qdrant_not_configured")

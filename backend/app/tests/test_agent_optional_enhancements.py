from app.models.mod import Mod
from app.services.agent.ranking.cross_encoder_reranker import CrossEncoderReranker
from app.services.agent.retrievers.qdrant_retriever import QdrantRetriever
from app.services.agent.search_types import SearchResult


def _result(title: str, score: int) -> SearchResult:
    return SearchResult(
        score=score,
        mod=Mod(
            source="nexusmods",
            external_id=title,
            game="Stellar Blade",
            title=title,
            url="https://example.com",
            first_seen_at="2025-01-01T00:00:00",
            last_seen_at="2025-01-01T00:00:00",
        ),
        tool_name="test",
    )


def test_qdrant_retriever_gracefully_degrades_when_disabled():
    retriever = QdrantRetriever(enabled=False)

    result = retriever.search(query="服装", filters={"game": "Stellar Blade"}, limit=5)

    assert result.results == []
    assert result.degraded_reason == "qdrant_disabled"


def test_cross_encoder_reranker_keeps_existing_order_when_disabled():
    results = [_result("A", 5), _result("B", 9)]

    reranked = CrossEncoderReranker(enabled=False).rerank("query", results)

    assert reranked == results

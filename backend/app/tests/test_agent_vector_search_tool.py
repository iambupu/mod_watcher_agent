from app.models.mod import Mod
from app.services.agent.retrievers.qdrant_retriever import QdrantSearchResult
from app.services.agent.search_types import SearchResult
from app.services.agent.tools.vector_search_tool import VectorSearchInput, VectorSearchTool


def test_vector_search_tool_emits_degraded_evidence_when_disabled():
    output = VectorSearchTool(enabled=False).run(
        VectorSearchInput(query="bimbo", filters={"keywords": ["bimbo"], "limit": 8}, limit=8, evidence_id="ev_test")
    )

    assert output.results == []
    assert output.degraded_reason == "qdrant_disabled"
    assert output.evidence == [
        {
            "fragment_id": "r_vector_1",
            "stage": "vector_retrieval",
            "tool": "qdrant_vector",
            "status": "degraded",
            "count": 0,
            "evidence_id": "ev_test",
            "reason": "qdrant_disabled",
            "fields": ["keywords"],
        }
    ]


def test_vector_search_tool_emits_success_evidence_when_retriever_returns_results(monkeypatch):
    mod = Mod(
        source="nexusmods",
        external_id="bimbo-vector",
        game="Skyrim Special Edition",
        title="Vector Bimbo Match",
        url="https://example.com/vector-bimbo",
    )
    result = SearchResult(score=7, mod=mod, tool_name="qdrant_vector")

    def fake_search(self, *, query, filters, limit):
        return QdrantSearchResult(results=[result], degraded_reason=None)

    monkeypatch.setattr("app.services.agent.retrievers.qdrant_retriever.QdrantRetriever.search", fake_search)

    output = VectorSearchTool(enabled=True).run(
        VectorSearchInput(query="bimbo", filters={"keywords": ["bimbo"], "games": ["Skyrim Special Edition"]}, limit=8, evidence_id="ev_test")
    )

    assert output.results == [result]
    assert output.degraded_reason is None
    assert output.evidence[0]["stage"] == "vector_retrieval"
    assert output.evidence[0]["tool"] == "qdrant_vector"
    assert output.evidence[0]["status"] == "succeeded"
    assert output.evidence[0]["count"] == 1
    assert output.evidence[0]["evidence_id"] == "ev_test"
    assert output.evidence[0]["fields"] == ["keywords", "games"]

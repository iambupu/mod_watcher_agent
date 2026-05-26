from app.services.agent.search_types import SearchResult


class CrossEncoderReranker:
    def __init__(self, *, enabled: bool = False, model_path: str | None = None):
        self.enabled = enabled
        self.model_path = model_path

    def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        if not self.enabled or not self.model_path:
            return results
        return results

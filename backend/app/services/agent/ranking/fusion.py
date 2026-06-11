from dataclasses import replace

from app.services.agent.search_types import SearchResult


def fuse_duplicate_results(results: list[SearchResult]) -> SearchResult:
    best = max(results, key=lambda item: item.score)
    tool_names = sorted({item.tool_name for item in results})
    retrieval_branch = "current_only" if any(item.retrieval_branch == "current_only" for item in results) else best.retrieval_branch
    max_score = max(item.score for item in results)
    source_bonus = max(0, len(tool_names) - 1) * 2
    score_breakdown = {
        "keyword_score": max_score,
        "semantic_score": 0,
        "freshness_score": _freshness_score(best),
        "popularity_score": _popularity_score(best),
        "preference_score": 0,
        "source_confidence": len(tool_names),
    }
    final_score = max_score + source_bonus + score_breakdown["freshness_score"] + score_breakdown["popularity_score"]
    return replace(
        best,
        score=final_score,
        score_breakdown=score_breakdown,
        rank_reason=f"命中工具：{', '.join(tool_names)}；基础相关性 {max_score}。",
        retrieval_branch=retrieval_branch,
    )


def _freshness_score(result: SearchResult) -> int:
    return 1 if result.mod.updated_at_remote else 0


def _popularity_score(result: SearchResult) -> int:
    values = [result.mod.downloads, result.mod.endorsements, result.mod.likes]
    return 1 if any((value or 0) > 0 for value in values) else 0

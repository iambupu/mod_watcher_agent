from __future__ import annotations

import pytest

from app.services.agent.schemas import AgentModMatch
from app.services.agent.self_correction.self_correction_schema import LLMSelfCorrectionReviewResult
from app.services.agent.workflows import self_correction_stages


def _match(match_id: int, title: str = "Direct Outfit") -> AgentModMatch:
    return AgentModMatch(
        id=match_id,
        title=title,
        source="nexusmods",
        game="Skyrim Special Edition",
        author="",
        version="",
        updated_at_remote=None,
        url=f"https://example.com/{match_id}",
        summary="Female outfit candidate.",
        score=0.0,
        rank_reason="semantic judge",
    )


@pytest.mark.asyncio
async def test_self_correction_stage_runs_llm_review_as_required_path(monkeypatch):
    seen = {}

    class FakeReviewTool:
        async def run(self, tool_input):
            seen["input"] = tool_input
            return LLMSelfCorrectionReviewResult(
                status="passed",
                used_llm=True,
                action="continue_answer",
                reason_summary="candidate set is consistent with the contract",
            )

    monkeypatch.setattr(self_correction_stages, "LLMSelfCorrectionReviewTool", FakeReviewTool)

    update = await self_correction_stages.self_correction_review_stage(
        "session",
        query="只看某类主结果",
        query_plan={
            "_agent_self_correction_config": {"enabled": True, "llm_review_required": True, "max_rounds": 2},
            "_agent_candidate_semantic_judge": {
                "fit_counts": {"direct_match": 1, "support_context": 0, "off_scope": 0, "uncertain": 0},
                "judgements": [{"candidate_id": 1, "fit_type": "direct_match"}],
            },
        },
        matches=[_match(1)],
        staged_results=["staged"],
        online_results=[],
        retrieval_summary={"mode": "local_plus_web", "staged_count": 1},
        retrieval_evidence=[{"tool": "ranker"}],
        tool_plan={"parallel_groups": []},
        llm={"available": True, "provider": "test", "model": "m"},
        evidence_id="ev_review",
    )

    assert seen["input"].round_index == 1
    assert seen["input"].phase == "round_review"
    assert seen["input"].evidence.retrieval_summary == {
        "mode": "local_plus_web",
    }
    assert update["matches"][0].title == "Direct Outfit"
    assert update["self_correction_summary"] == {
        "status": "answered",
        "round_count": 1,
        "llm_review_required": True,
    }
    assert update["query_plan"]["_agent_self_correction_trace"]["rounds"][0]["used_llm"] is True
    assert any(item.get("tool") == "self_correction_review" for item in update["retrieval_evidence"])


@pytest.mark.asyncio
async def test_self_correction_stage_repairs_plan_and_reranks(monkeypatch):
    review_calls = []
    retrieval_seen = {}
    ranking_seen = {}

    class FakeReviewTool:
        async def run(self, tool_input):
            review_calls.append(tool_input.round_index)
            if tool_input.round_index == 1:
                return LLMSelfCorrectionReviewResult(
                    status="passed",
                    used_llm=True,
                    action="repair_query_plan",
                    reason_summary="query plan contains polluted category",
                    correction_plan={
                        "remove_fields": ["categories"],
                        "query_plan": {"keywords": ["female outfit"], "categories": ["Clothing"]},
                    },
                    gaps=["polluted_category"],
                )
            return LLMSelfCorrectionReviewResult(
                status="passed",
                used_llm=True,
                action="continue_answer",
                reason_summary="repaired result is usable",
            )

    async def fake_execute_retrieval_stage(session, *, query, query_plan, tool_plan, evidence_id):
        retrieval_seen["query_plan"] = query_plan
        return {
            "retrieval_evidence": [{"tool": "refined_retrieval", "evidence_id": evidence_id}],
            "staged_results": ["refined"],
            "online_results": [],
        }

    async def fake_rank_candidates_stage(
        session,
        *,
        query,
        query_plan,
        staged_results,
        online_results,
        retrieval_evidence,
        llm,
        evidence_id,
    ):
        ranking_seen["query_plan"] = query_plan
        ranking_seen["staged_results"] = staged_results
        return {
            "query_plan": {
                **query_plan,
                "_agent_candidate_semantic_judge": {
                    "fit_counts": {"direct_match": 1, "support_context": 0, "off_scope": 0, "uncertain": 0},
                    "judgements": [{"candidate_id": 2, "fit_type": "direct_match"}],
                },
            },
            "matches": [_match(2, "Repaired Outfit")],
            "retrieval_evidence": [*retrieval_evidence, {"tool": "rerank", "evidence_id": evidence_id}],
        }

    monkeypatch.setattr(self_correction_stages, "LLMSelfCorrectionReviewTool", FakeReviewTool)
    monkeypatch.setattr(self_correction_stages, "execute_retrieval_stage", fake_execute_retrieval_stage)
    monkeypatch.setattr(self_correction_stages, "rank_candidates_stage", fake_rank_candidates_stage)

    update = await self_correction_stages.self_correction_review_stage(
        "session",
        query="只看天际女性服装",
            query_plan={
                "games": ["skyrimspecialedition"],
                "sources": ["nexusmods"],
                "categories": ["历史候选标题污染"],
                "_agent_self_correction_config": {"enabled": True, "llm_review_required": True, "max_rounds": 2},
                "_agent_semantic_strategy": {
                "direct_match_definition": ["female outfit"],
                "support_context_definition": ["body preset"],
                "hard_filters": {"games": ["skyrimspecialedition"], "sources": ["nexusmods"]},
            },
        },
        matches=[_match(1, "Polluted Support")],
        staged_results=["old"],
        online_results=[],
        retrieval_summary={"mode": "local_only", "staged_count": 1},
        retrieval_evidence=[{"tool": "ranker"}],
        tool_plan={"parallel_groups": [{"name": "local"}]},
        llm={"available": True, "provider": "test", "model": "m"},
        evidence_id="ev_repair",
    )

    assert review_calls == [1, 2]
    assert retrieval_seen["query_plan"]["categories"] == ["Clothing"]
    assert retrieval_seen["query_plan"]["games"] == ["skyrimspecialedition"]
    assert retrieval_seen["query_plan"]["sources"] == ["nexusmods"]
    assert "female outfit" in retrieval_seen["query_plan"]["keywords"]
    assert ranking_seen["staged_results"] == ["refined"]
    assert update["matches"][0].title == "Repaired Outfit"
    rounds = update["query_plan"]["_agent_self_correction_trace"]["rounds"]
    assert rounds[0]["repair"]["removed_pollution"] == ["removed_field:categories"]
    assert rounds[0]["post_correction_match_count"] == 1
    assert update["self_correction_summary"]["round_count"] == 2


@pytest.mark.asyncio
async def test_self_correction_stage_falls_back_when_max_round_still_requests_correction(monkeypatch):
    class FakeReviewTool:
        async def run(self, tool_input):
            return LLMSelfCorrectionReviewResult(
                status="passed",
                used_llm=True,
                action="refine_retrieval",
                reason_summary="still no safe direct match",
            )

    async def fake_execute_retrieval_stage(session, *, query, query_plan, tool_plan, evidence_id):
        return {
            "retrieval_evidence": [{"tool": "refined_retrieval", "evidence_id": evidence_id}],
            "staged_results": ["refined"],
            "online_results": [],
        }

    async def fake_rank_candidates_stage(
        session,
        *,
        query,
        query_plan,
        staged_results,
        online_results,
        retrieval_evidence,
        llm,
        evidence_id,
    ):
        return {
            "query_plan": query_plan,
            "matches": [_match(2, "Unverified Outfit")],
            "retrieval_evidence": retrieval_evidence,
        }

    monkeypatch.setattr(self_correction_stages, "LLMSelfCorrectionReviewTool", FakeReviewTool)
    monkeypatch.setattr(self_correction_stages, "execute_retrieval_stage", fake_execute_retrieval_stage)
    monkeypatch.setattr(self_correction_stages, "rank_candidates_stage", fake_rank_candidates_stage)

    update = await self_correction_stages.self_correction_review_stage(
        "session",
        query="只看某类主结果",
        query_plan={
            "_agent_self_correction_config": {"enabled": True, "llm_review_required": True, "max_rounds": 1},
        },
        matches=[_match(1)],
        staged_results=["old"],
        online_results=[],
        retrieval_summary={"mode": "local_only"},
        retrieval_evidence=[{"tool": "ranker"}],
        tool_plan={"parallel_groups": []},
        llm={"available": True, "provider": "test", "model": "m"},
        evidence_id="ev_max_round",
    )

    assert update["self_correction_summary"]["status"] == "fallback"
    assert update["query_plan"]["_agent_self_correction_trace"]["final_status"] == "fallback"

import pytest

from app.services.agent.schemas import AgentModMatch
from app.services.agent.search_types import SearchPlan
from app.services.agent.tools.candidate_recovery_tool import (
    CandidateRecoveryInput,
    CandidateRecoveryTool,
)
from app.services.agent.tools.local_db_search_tool import LocalDbSearchTool
from app.services.agent.tools.match_materializer_tool import (
    MatchMaterializerOutput,
    MatchMaterializerTool,
)
from app.services.agent.tools.result_fusion_ranker_tool import (
    ResultFusionRankerOutput,
    ResultFusionRankerTool,
)


def _match() -> AgentModMatch:
    return AgentModMatch(
        id=1,
        title="Recovered Mod",
        source="nexusmods",
        game="Skyrim Special Edition",
        author=None,
        version=None,
        url="https://example.com/recovered",
        updated_at_remote=None,
        score=2,
    )


@pytest.mark.asyncio
async def test_candidate_recovery_clears_keywords_and_emits_evidence(monkeypatch):
    captured = {}

    async def fake_local_run(self, tool_input):
        captured["local_query"] = tool_input.query
        captured["retry_plan"] = tool_input.plan.to_query_plan()
        captured["local_evidence_id"] = tool_input.evidence_id
        return ["candidate"]

    def fake_ranker_run(self, tool_input):
        captured["ranker_plan"] = tool_input.plan.to_query_plan()
        captured["ranker_emit_evidence"] = tool_input.emit_evidence
        captured["ranker_apply_distinctive_filter"] = tool_input.apply_distinctive_filter
        return ResultFusionRankerOutput(results=list(tool_input.staged_results), evidence=[])

    def fake_materializer_run(self, tool_input):
        captured["materializer_limit"] = tool_input.limit
        captured["materializer_evidence_id"] = tool_input.evidence_id
        return MatchMaterializerOutput(matches=[_match()])

    monkeypatch.setattr(LocalDbSearchTool, "run", fake_local_run)
    monkeypatch.setattr(ResultFusionRankerTool, "run", fake_ranker_run)
    monkeypatch.setattr(MatchMaterializerTool, "run", fake_materializer_run)

    output = await CandidateRecoveryTool(session=object()).run(
        CandidateRecoveryInput(
            query="有什么相关风格的mod",
            search_query="相关风格",
            query_plan={"keywords": ["bimbo"], "sort_field": "updated_at_remote", "sort_order": "desc", "limit": 5},
            plan=SearchPlan.from_query_plan({"keywords": ["bimbo"], "limit": 8, "sort_field": "relevance"}),
            evidence_id="ev_recovery",
        )
    )

    assert [match.title for match in output.matches] == ["Recovered Mod"]
    assert captured["local_query"] == "相关风格"
    assert captured["retry_plan"]["keywords"] == []
    assert captured["retry_plan"]["sort_field"] == "updated_at_remote"
    assert captured["retry_plan"]["sort_order"] == "desc"
    assert captured["retry_plan"]["limit"] == 5
    assert captured["local_evidence_id"] == "ev_recovery"
    assert captured["ranker_plan"]["keywords"] == []
    assert captured["ranker_emit_evidence"] is False
    assert captured["ranker_apply_distinctive_filter"] is False
    assert captured["materializer_limit"] == 5
    assert captured["materializer_evidence_id"] == "ev_recovery"
    assert output.evidence == [
        {
            "fragment_id": "r_candidate_recovery_1",
            "stage": "candidate_recovery",
            "tool": "candidate_recovery",
            "status": "succeeded",
            "count": 1,
            "reason": "no_validated_matches",
            "evidence_id": "ev_recovery",
            "fields": ["keywords", "sort_field", "sort_order", "limit"],
        }
    ]

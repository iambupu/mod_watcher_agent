import pytest

from app.services.agent.schemas import AgentModMatch
from app.services.agent.tools.candidate_ranking_tool import (
    CandidateRankingInput,
    CandidateRankingTool,
)
from app.services.agent.tools.candidate_recovery_tool import (
    CandidateRecoveryOutput,
    CandidateRecoveryTool,
)
from app.services.agent.tools.match_materializer_tool import (
    MatchMaterializerOutput,
    MatchMaterializerTool,
)
from app.services.agent.tools.result_fusion_ranker_tool import (
    ResultFusionRankerOutput,
    ResultFusionRankerTool,
)


def _match(title: str) -> AgentModMatch:
    return AgentModMatch(
        id=1,
        title=title,
        source="nexusmods",
        game="Skyrim Special Edition",
        author=None,
        version=None,
        url="https://example.com/mod",
        updated_at_remote=None,
        score=2,
    )


@pytest.mark.asyncio
async def test_candidate_ranking_merges_evidence_and_recovers_when_validator_drops_matches(monkeypatch):
    captured = {}

    def fake_fusion_run(self, tool_input):
        captured["fusion_query"] = tool_input.query
        captured["fusion_evidence_id"] = tool_input.evidence_id
        return ResultFusionRankerOutput(
            results=["ranked"],
            evidence=[{"fragment_id": "r_fusion_1", "stage": "final_ranking", "evidence_id": tool_input.evidence_id}],
        )

    def fake_materializer_run(self, tool_input):
        captured["materializer_results"] = tool_input.results
        captured["materializer_evidence_id"] = tool_input.evidence_id
        return MatchMaterializerOutput(matches=[_match("Initial Match")])

    async def fake_validator(**kwargs):
        captured["validator_query_plan"] = kwargs["query_plan"]
        return []

    async def fake_recovery_run(self, tool_input):
        captured["recovery_plan_keywords"] = tool_input.plan.keywords
        captured["recovery_evidence_id"] = tool_input.evidence_id
        return CandidateRecoveryOutput(
            matches=[_match("Recovered Match")],
            evidence=[
                {
                    "fragment_id": "r_candidate_recovery_1",
                    "stage": "candidate_recovery",
                    "evidence_id": tool_input.evidence_id,
                }
            ],
        )

    monkeypatch.setattr(ResultFusionRankerTool, "run", fake_fusion_run)
    monkeypatch.setattr(MatchMaterializerTool, "run", fake_materializer_run)
    monkeypatch.setattr(CandidateRecoveryTool, "run", fake_recovery_run)

    output = await CandidateRankingTool(session=object(), validator=fake_validator).run(
        CandidateRankingInput(
            query="有什么相关风格的mod",
            query_plan={"keywords": ["bimbo"], "limit": 5, "evidence_id": "ev_rank"},
            prior_evidence=[{"fragment_id": "r_exec_1", "stage": "local_retrieval", "evidence_id": "ev_rank"}],
            llm_available=True,
        )
    )

    assert [match.title for match in output.matches] == ["Recovered Match"]
    assert output.match_count == 1
    assert output.validator_status == "succeeded"
    assert captured["fusion_query"] == "有什么相关风格的mod"
    assert captured["fusion_evidence_id"] == "ev_rank"
    assert captured["materializer_results"] == ["ranked"]
    assert captured["materializer_evidence_id"] == "ev_rank"
    assert captured["validator_query_plan"]["keywords"] == ["bimbo"]
    assert captured["recovery_plan_keywords"] == ["bimbo"]
    assert captured["recovery_evidence_id"] == "ev_rank"
    assert [item["fragment_id"] for item in output.evidence] == [
        "r_exec_1",
        "r_fusion_1",
        "r_candidate_recovery_1",
    ]

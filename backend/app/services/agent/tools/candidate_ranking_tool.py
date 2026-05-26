from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from app.services.agent.search_types import SearchPlan
from app.services.agent.tools.candidate_recovery_tool import (
    CandidateRecoveryInput,
    CandidateRecoveryTool,
)
from app.services.agent.tools.llm_candidate_validator_tool import (
    LlmCandidateValidatorInput,
    LlmCandidateValidatorOutput,
    LlmCandidateValidatorTool,
)
from app.services.agent.tools.match_materializer_tool import (
    MatchMaterializerInput,
    MatchMaterializerTool,
)
from app.services.agent.tools.result_fusion_ranker_tool import (
    ResultFusionRankerInput,
    ResultFusionRankerTool,
)


@dataclass(frozen=True)
class CandidateRankingInput:
    query: str
    query_plan: dict[str, Any]
    staged_results: list = field(default_factory=list)
    online_results: list = field(default_factory=list)
    prior_evidence: list[dict[str, object]] = field(default_factory=list)
    llm_available: bool = False
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    evidence_id: str = ""


@dataclass(frozen=True)
class CandidateRankingOutput:
    matches: list
    evidence: list[dict[str, object]]
    match_count: int
    validator_status: str


class CandidateRankingTool:
    """Agent tool for candidate fusion, materialization, validation, and recovery."""

    name = "candidate_ranking"

    def __init__(self, session: Session, *, validator=None):
        self.session = session
        self.validator = validator

    async def run(self, tool_input: CandidateRankingInput) -> CandidateRankingOutput:
        query_plan = dict(tool_input.query_plan or {})
        evidence_id = tool_input.evidence_id or str(query_plan.get("evidence_id") or "").strip()
        plan = SearchPlan.from_query_plan(query_plan)
        fusion_output = ResultFusionRankerTool().run(
            ResultFusionRankerInput(
                query=tool_input.query,
                query_plan=query_plan,
                plan=plan,
                staged_results=tool_input.staged_results,
                online_results=tool_input.online_results,
                evidence_id=evidence_id,
            )
        )
        matches = MatchMaterializerTool(self.session).run(
            MatchMaterializerInput(results=fusion_output.results, limit=plan.limit, evidence_id=evidence_id)
        ).matches
        validator_output = await self._validate(tool_input, query_plan, matches, evidence_id)
        matches = validator_output.matches
        recovery_evidence: list[dict[str, object]] = []
        if not matches:
            recovery_output = await CandidateRecoveryTool(self.session).run(
                CandidateRecoveryInput(
                    query=tool_input.query,
                    search_query=tool_input.query,
                    query_plan=query_plan,
                    plan=plan,
                    evidence_id=evidence_id,
                )
            )
            matches = recovery_output.matches
            recovery_evidence = recovery_output.evidence
        evidence = [
            *tool_input.prior_evidence,
            *fusion_output.evidence,
            *recovery_evidence,
        ]
        return CandidateRankingOutput(
            matches=matches,
            evidence=evidence,
            match_count=len(matches),
            validator_status=validator_output.status,
        )

    async def _validate(
        self,
        tool_input: CandidateRankingInput,
        query_plan: dict[str, Any],
        matches: list,
        evidence_id: str,
    ) -> LlmCandidateValidatorOutput:
        validator_tool = (
            LlmCandidateValidatorTool(validator=self.validator)
            if self.validator is not None
            else LlmCandidateValidatorTool()
        )
        return await validator_tool.run(
            LlmCandidateValidatorInput(
                query=tool_input.query,
                matches=matches,
                llm_available=tool_input.llm_available,
                provider=tool_input.provider,
                api_key=tool_input.api_key,
                base_url=tool_input.base_url,
                model=tool_input.model,
                query_plan=query_plan,
                evidence_id=evidence_id,
            )
        )

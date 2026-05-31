import logging
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from app.services.agent.planning.slot_normalization import normalize_limit
from app.services.agent.query_planner import DEFAULT_AGENT_LIMIT
from app.services.agent.schemas import AgentModMatch
from app.services.agent.search_types import SearchPlan
from app.services.agent.tools.local_db_search_tool import (
    LocalDbSearchTool,
    local_db_input_from_plan,
)
from app.services.agent.tools.match_materializer_tool import (
    MatchMaterializerInput,
    MatchMaterializerTool,
)
from app.services.agent.tools.result_fusion_ranker_tool import (
    ResultFusionRankerInput,
    ResultFusionRankerTool,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CandidateRecoveryInput:
    query: str
    search_query: str
    query_plan: dict[str, Any]
    plan: SearchPlan
    evidence_id: str = ""


@dataclass(frozen=True)
class CandidateRecoveryOutput:
    matches: list[AgentModMatch] = field(default_factory=list)
    evidence: list[dict[str, object]] = field(default_factory=list)


class CandidateRecoveryTool:
    """候选校验后为空时执行窄范围本地恢复检索。"""

    name = "candidate_recovery"

    def __init__(self, session: Session):
        self.session = session

    async def run(self, tool_input: CandidateRecoveryInput) -> CandidateRecoveryOutput:
        retry_plan = _build_retry_plan(tool_input.query_plan, tool_input.plan, tool_input.evidence_id)
        retry_search_plan = SearchPlan.from_query_plan(retry_plan)
        retry_results = await LocalDbSearchTool(self.session).run(
            local_db_input_from_plan(tool_input.search_query, retry_plan)
        )
        retry_output = ResultFusionRankerTool().run(
            ResultFusionRankerInput(
                query=tool_input.query,
                query_plan=tool_input.query_plan,
                plan=retry_search_plan,
                staged_results=retry_results,
                online_results=[],
                evidence_id=tool_input.evidence_id,
                emit_evidence=False,
                apply_distinctive_filter=retry_search_plan.sort_field == "relevance",
            )
        )
        matches = MatchMaterializerTool(self.session).run(
            MatchMaterializerInput(
                results=retry_output.results,
                limit=retry_search_plan.limit,
                evidence_id=tool_input.evidence_id,
            )
        ).matches
        status = "succeeded" if matches else "empty"
        logger.info(
            "agent.tool name=candidate_recovery status=%s results=%s original_keywords=%s retry_sort=%s/%s evidence_id=%s",
            status,
            len(matches),
            tool_input.plan.keywords,
            retry_search_plan.sort_field,
            retry_search_plan.sort_order,
            tool_input.evidence_id,
        )
        return CandidateRecoveryOutput(
            matches=matches,
            evidence=[
                {
                    "fragment_id": "r_candidate_recovery_1",
                    "stage": "candidate_recovery",
                    "tool": self.name,
                    "status": status,
                    "count": len(matches),
                    "reason": "no_validated_matches",
                    "evidence_id": tool_input.evidence_id,
                    "fields": ["keywords", "sort_field", "sort_order", "limit"],
                }
            ],
        )


def _build_retry_plan(query_plan: dict[str, Any], plan: SearchPlan, evidence_id: str) -> dict[str, Any]:
    retry_plan = dict(plan.to_query_plan())
    retry_plan["evidence_id"] = evidence_id
    retry_plan["keywords"] = []
    retry_plan["sort_field"] = query_plan.get("sort_field") or "updated_at_remote"
    retry_plan["sort_order"] = query_plan.get("sort_order") or "desc"
    retry_plan["limit"] = normalize_limit(query_plan, default=plan.limit or DEFAULT_AGENT_LIMIT, maximum=20)
    return retry_plan

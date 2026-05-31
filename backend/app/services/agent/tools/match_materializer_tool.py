import logging
from dataclasses import dataclass, field

from sqlmodel import Session

from app.services.agent.mod_search_service import build_summary_map
from app.services.agent.response_builder import match_from_mod
from app.services.agent.schemas import AgentModMatch
from app.services.agent.search_types import SearchResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchMaterializerInput:
    results: list[SearchResult] = field(default_factory=list)
    limit: int = 8
    evidence_id: str = ""


@dataclass(frozen=True)
class MatchMaterializerOutput:
    matches: list[AgentModMatch]


class MatchMaterializerTool:
    """把排序后的检索结果转换为前端稳定消费的 `AgentModMatch`。"""

    name = "match_materializer"

    def __init__(self, session: Session):
        self.session = session

    def run(self, tool_input: MatchMaterializerInput) -> MatchMaterializerOutput:
        top = tool_input.results[: max(0, tool_input.limit)]
        mod_ids = [item.mod.id for item in top if item.mod.id is not None]
        summary_by_mod = build_summary_map(self.session, mod_ids)
        matches = []
        for item in top:
            match = match_from_mod(item.mod, item.score, summary_by_mod)
            match.score_breakdown = item.score_breakdown
            match.rank_reason = item.rank_reason
            matches.append(match)
        logger.info(
            "agent.tool name=match_materializer status=succeeded input=%s output=%s summaries=%s evidence_id=%s",
            len(tool_input.results),
            len(matches),
            len(summary_by_mod),
            tool_input.evidence_id,
        )
        return MatchMaterializerOutput(matches=matches)

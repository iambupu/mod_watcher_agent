import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.response_builder import build_response_cards
from app.services.agent.schemas import AgentModMatch

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResponseCardBuilderInput:
    query: str
    query_plan: dict[str, Any] | None = None
    matches: list[AgentModMatch] = field(default_factory=list)
    next_steps: list[str] | None = None
    evidence_id: str = ""


@dataclass(frozen=True)
class ResponseCardBuilderOutput:
    cards: dict[str, list[str]]


class ResponseCardBuilderTool:
    """构建标准 response cards，保持前端展示和质量门契约一致。"""

    name = "response_card_builder"

    def run(self, tool_input: ResponseCardBuilderInput) -> ResponseCardBuilderOutput:
        cards = build_response_cards(
            query=tool_input.query,
            query_plan=tool_input.query_plan,
            matches=tool_input.matches,
            next_steps=tool_input.next_steps,
        )
        logger.info(
            "agent.tool name=response_card_builder status=succeeded matches=%s filters=%s next_steps=%s evidence_id=%s",
            len(tool_input.matches),
            len(cards.get("filters") or []),
            len(cards.get("next_steps") or []),
            tool_input.evidence_id,
        )
        return ResponseCardBuilderOutput(cards=cards)

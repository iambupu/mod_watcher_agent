import logging

from app.services.agent.context.context_store import AgentContextSnapshot
from app.services.agent.context.context_summarizer import summarize_agent_context
from app.services.agent.schemas import AgentChatRequest, AgentModDetailRequest

logger = logging.getLogger(__name__)


class ContextSummaryTool:
    """Agent tool for compacting request history into actionable context."""

    name = "context_summary"

    def run(
        self,
        request: AgentChatRequest | AgentModDetailRequest,
        *,
        recent_message_count: int = 5,
        evidence_id: str = "",
    ) -> AgentContextSnapshot:
        context = summarize_agent_context(request, recent_message_count=recent_message_count)
        logger.info(
            "agent.tool name=context_summary status=succeeded constraints=%s last_query_has_keywords=%s shown_mod_titles=%s evidence_id=%s",
            list((context.get("active_constraints") or {}).keys()),
            bool((context.get("last_query_context") or {}).get("keywords")),
            len(context.get("shown_mod_titles") or []),
            evidence_id,
        )
        return context

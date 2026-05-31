from typing import Literal, NotRequired, TypedDict

from fastapi import Request

from app.services.agent.context.context_store import AgentContextSnapshot
from app.services.agent.planning.query_diagnosis import QueryDiagnosis
from app.services.agent.planning.tool_planner import ToolPlan
from app.services.agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentModDetailRequest,
    AgentModMatch,
)
from app.services.agent.search_types import SearchResult
from app.services.agent.tracing.search_trace import TraceEvent


class AgentGraphState(TypedDict):
    request_kind: Literal["chat", "mod_detail"]
    fastapi_request: Request
    chat_request: NotRequired[AgentChatRequest | None]
    detail_request: NotRequired[AgentModDetailRequest | None]
    active_session_id: NotRequired[str | None]
    evidence_id: NotRequired[str]
    running_summary: NotRequired[str]
    last_query_context: NotRequired[dict[str, object]]
    shown_mod_titles: NotRequired[list[str]]
    preferences: NotRequired[dict[str, object]]
    memory_context: NotRequired[dict[str, object]]
    semantic_strategy: NotRequired[dict[str, object]]
    query_plan: NotRequired[dict[str, object]]
    query_diagnosis: NotRequired[QueryDiagnosis]
    tool_plan: NotRequired[ToolPlan]
    active_constraints: NotRequired[dict[str, object]]
    retrieval_summary: NotRequired[dict[str, object]]
    ranking_summary: NotRequired[dict[str, object]]
    retrieval_evidence: NotRequired[list[dict[str, object]]]
    staged_results: NotRequired[list[SearchResult]]
    online_results: NotRequired[list[SearchResult]]
    matches: NotRequired[list[AgentModMatch]]
    llm_available: NotRequired[bool]
    llm_provider: NotRequired[str]
    llm_api_key: NotRequired[str]
    llm_base_url: NotRequired[str]
    llm_model: NotRequired[str]
    tool_traces: NotRequired[list[object]]
    reflection_notes: NotRequired[list[object]]
    context_snapshot: NotRequired[AgentContextSnapshot]
    response: NotRequired[AgentChatResponse | None]
    trace: NotRequired[list[TraceEvent]]
    errors: NotRequired[list[str]]

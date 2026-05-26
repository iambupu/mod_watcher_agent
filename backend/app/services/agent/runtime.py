import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request
from sqlmodel import Session

from app.services.agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentModDetailRequest,
)
from app.services.agent.tools.chat_request_guard_tool import (
    ChatRequestGuardInput,
    ChatRequestGuardTool,
)
from app.services.agent.tracing.search_trace import TraceEvent
from app.services.agent.workflows.mod_search_graph import run_agent_graph
from app.services.agent.workflows.response_finalization import finalize_chat_response

logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(self, session: Session):
        """Initialize the runtime with request-scoped dependencies."""
        self.session = session
        self.last_trace: list[TraceEvent] = []

    async def chat(self, body: AgentChatRequest, request: Request) -> AgentChatResponse:
        evidence_id = _new_evidence_id()
        guarded = ChatRequestGuardTool().run(ChatRequestGuardInput(request=body, evidence_id=evidence_id))
        if guarded.response is not None:
            return guarded.response
        state = await self._run_graph(
            request_kind="chat",
            state={
                "request_kind": "chat",
                "evidence_id": evidence_id,
                "chat_request": body,
                "detail_request": None,
                "fastapi_request": request,
                "response": None,
                "trace": [],
                "errors": [],
            },
        )
        self.last_trace = state.get("trace", [])
        response = state.get("response")
        if response is None:
            raise RuntimeError("Agent graph completed without a chat response")
        return finalize_chat_response(
            self.session,
            request=body,
            response=response,
            graph_state=state,
            fallback_evidence_id=evidence_id,
        )

    async def ask_mod_detail(
        self,
        body: AgentModDetailRequest,
        request: Request,
    ) -> AgentChatResponse:
        evidence_id = _new_evidence_id()
        state = await self._run_graph(
            request_kind="mod_detail",
            state={
                "request_kind": "mod_detail",
                "evidence_id": evidence_id,
                "chat_request": None,
                "detail_request": body,
                "fastapi_request": request,
                "response": None,
                "trace": [],
                "errors": [],
            },
        )
        self.last_trace = state.get("trace", [])
        response = state.get("response")
        if response is None:
            raise RuntimeError("Agent graph completed without a detail response")
        return response

    async def _run_graph(self, request_kind: str, state: dict) -> dict:
        started_at = perf_counter()
        logger.info("agent.runtime request_kind=%s status=started", request_kind)
        try:
            result = await run_agent_graph(self.session, state)
        except Exception as exc:
            logger.info(
                "agent.runtime request_kind=%s status=failed duration_ms=%s error_type=%s",
                request_kind,
                _elapsed_ms(started_at),
                type(exc).__name__,
            )
            raise
        response = result.get("response")
        trace = result.get("trace") or []
        logger.info(
            "agent.runtime request_kind=%s status=succeeded duration_ms=%s trace_steps=%s matches=%s",
            request_kind,
            _elapsed_ms(started_at),
            len(trace),
            len(response.matches) if response is not None else 0,
        )
        return result


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _new_evidence_id() -> str:
    return f"ev_{uuid4().hex[:12]}"

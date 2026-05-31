import logging
from typing import Any

from sqlmodel import Session

from app.services.agent.memory.evidence_service import (
    build_memory_evidence,
    build_memory_writeback_evidence,
    link_understanding_to_evidence,
)
from app.services.agent.reflection.audit_service import (
    annotate_action_evidence_consistency,
    apply_consistency_guard,
    build_standard_audit,
)
from app.services.agent.reflection.response_enrichment import apply_query_understanding_to_response
from app.services.agent.schemas import AgentAudit, AgentChatRequest, AgentChatResponse
from app.services.agent.tools.memory_writeback_tool import MemoryWritebackInput, MemoryWritebackTool

logger = logging.getLogger(__name__)


def finalize_chat_response(
    session: Session,
    *,
    request: AgentChatRequest,
    response: AgentChatResponse,
    graph_state: dict[str, Any],
    fallback_evidence_id: str,
) -> AgentChatResponse:
    query_plan = graph_state.get("query_plan") if isinstance(graph_state.get("query_plan"), dict) else {}
    evidence_id = str(query_plan.get("evidence_id") or fallback_evidence_id)
    # 公开 understanding 来自诊断和 query_plan，不暴露 LLM 原始推理过程。
    apply_query_understanding_to_response(response, graph_state.get("query_diagnosis"), query_plan)
    response.evidence_id = evidence_id
    response.memory_evidence = build_memory_evidence(graph_state.get("memory_context"), evidence_id=evidence_id)
    if not response.memory_evidence:
        response.memory_evidence = []
    # 写回的是下一轮可复用的上下文事实；它不是长期事实源的唯一依据。
    writeback = MemoryWritebackTool(session).run(
        MemoryWritebackInput(
            query=request.message,
            query_plan=query_plan,
            understanding=response.understanding if isinstance(response.understanding, dict) else {},
            evidence_id=evidence_id,
        )
    )
    writeback_evidence = build_memory_writeback_evidence(writeback)
    if writeback_evidence:
        response.memory_evidence.extend(writeback_evidence)
    if not response.retrieval_evidence:
        response.retrieval_evidence = []
    link_understanding_to_evidence(response)
    # audit 是前端和质量门共同消费的 analysis -> evidence -> conclusion 契约。
    response.audit = build_standard_audit(response, graph_state.get("tool_plan")).model_dump(mode="python")
    apply_consistency_guard(response)
    annotate_action_evidence_consistency(response)
    response.audit = AgentAudit.model_validate(response.audit)
    logger.info(
        "agent.response_finalization status=succeeded evidence_id=%s memory_evidence=%s retrieval_evidence=%s",
        evidence_id,
        len(response.memory_evidence or []),
        len(response.retrieval_evidence or []),
    )
    return response

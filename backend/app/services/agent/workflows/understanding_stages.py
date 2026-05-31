from typing import Any

from fastapi import Request
from sqlmodel import Session

from app.services.agent.schemas import AgentChatRequest, AgentModDetailRequest
from app.services.agent.tools.mod_detail_answer_tool import (
    ModDetailAnswerInput,
    ModDetailAnswerTool,
)
from app.services.agent.tools.task_understanding_tool import (
    TaskUnderstandingInput,
    TaskUnderstandingTool,
)


async def diagnose_query_stage(
    session: Session | None,
    *,
    request: AgentChatRequest,
    fastapi_request: Request,
    active_constraints: dict[str, Any],
    last_query_context: dict[str, Any],
    shown_mod_titles: list[str],
    evidence_id: str,
) -> dict[str, Any]:
    output = await TaskUnderstandingTool(session).run(
        TaskUnderstandingInput(
            query=request.message,
            history=request.history,
            active_constraints=active_constraints,
            last_query_context=last_query_context,
            shown_mod_titles=shown_mod_titles,
            provider_override=request.provider_override,
            model_override=request.model_override,
            request=fastapi_request,
            evidence_id=evidence_id,
        )
    )
    effective_evidence_id = output.evidence_id or evidence_id
    return {
        "evidence_id": effective_evidence_id,
        "query_plan": output.query_plan,
        "query_diagnosis": output.query_diagnosis,
        "preferences": output.preferences,
        "memory_context": output.memory_context,
        "semantic_strategy": output.semantic_strategy,
        "llm_available": output.llm_available,
        "llm_provider": output.llm_provider,
        "llm_api_key": output.llm_api_key,
        "llm_base_url": output.llm_base_url,
        "llm_model": output.llm_model,
    }


async def generate_detail_answer_stage(
    session: Session,
    *,
    request_kind: str,
    detail_request: AgentModDetailRequest | None,
    fastapi_request: Request,
) -> dict[str, Any]:
    if request_kind == "chat":
        raise ValueError("chat graph runs must use the search workflow")
    if request_kind != "mod_detail":
        raise ValueError(f"unsupported agent request kind: {request_kind}")
    if detail_request is None:
        raise ValueError("detail_request is required for mod_detail graph runs")
    response = await ModDetailAnswerTool(session).run(
        ModDetailAnswerInput(
            mod_id=detail_request.mod_id,
            question=detail_request.question,
            history=detail_request.history,
            provider_override=detail_request.provider_override,
            model_override=detail_request.model_override,
            request=fastapi_request,
        )
    )
    return {"response": response}

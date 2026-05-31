import logging
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from sqlmodel import Session

from app.services.agent.context.context_stage import build_context_state_update
from app.services.agent.tools.tool_planner_tool import ToolPlannerInput, ToolPlannerTool
from app.services.agent.tracing.search_trace import (
    append_trace,
    elapsed_ms,
    fail_trace,
    finish_trace,
    start_trace,
)
from app.services.agent.workflows.graph_state import AgentGraphState
from app.services.agent.workflows.search_stages import (
    execute_retrieval_stage,
    generate_chat_answer_stage,
    rank_candidates_stage,
)
from app.services.agent.workflows.understanding_stages import (
    diagnose_query_stage,
    generate_detail_answer_stage,
)
from app.utils.numeric import safe_nonnegative_int

logger = logging.getLogger(__name__)


def _event_duration_ms(event: dict) -> int:
    return safe_nonnegative_int(event.get("duration_ms") if isinstance(event, dict) else None)


def _load_state(state: AgentGraphState) -> dict:
    started_at = start_trace()
    evidence_id = str(state.get("evidence_id") or "").strip() or f"ev_{uuid4().hex[:12]}"
    logger.info("agent.stage stage=load_state status=started evidence_id=%s", evidence_id)
    event = finish_trace("load_state", started_at, "Agent graph state loaded.", evidence_id=evidence_id)
    logger.info(
        "agent.stage stage=load_state status=succeeded duration_ms=%s evidence_id=%s",
        _event_duration_ms(event),
        evidence_id,
    )
    return {"evidence_id": evidence_id, "trace": append_trace(state.get("trace"), event)}


def _summarize_context(state: AgentGraphState) -> dict:
    started_at = start_trace()
    evidence_id = _state_evidence_id(state)
    logger.info("agent.stage stage=summarize_context status=started evidence_id=%s", evidence_id)
    body = state.get("chat_request") or state.get("detail_request")
    if body is None:
        return {
            "trace": append_trace(
                state.get("trace"),
                finish_trace(
                    "summarize_context",
                    started_at,
                    "No request body available for context summary.",
                    evidence_id=evidence_id,
                ),
            )
        }
    # 上下文摘要只产出可公开的任务状态和约束，不保存原始推理链。
    context_update = build_context_state_update(body, evidence_id=evidence_id)
    event = finish_trace("summarize_context", started_at, "Agent context summarized.", evidence_id=evidence_id)
    logger.info(
        "agent.stage stage=summarize_context status=succeeded duration_ms=%s evidence_id=%s",
        _event_duration_ms(event),
        evidence_id,
    )
    return {
        **context_update,
        "trace": append_trace(state.get("trace"), event),
    }


def _persist_result(state: AgentGraphState) -> dict:
    started_at = start_trace()
    evidence_id = _state_evidence_id(state)
    logger.info("agent.stage stage=persist_result status=started evidence_id=%s", evidence_id)
    event = finish_trace("persist_result", started_at, "Agent graph result prepared.", evidence_id=evidence_id)
    logger.info(
        "agent.stage stage=persist_result status=succeeded duration_ms=%s evidence_id=%s",
        _event_duration_ms(event),
        evidence_id,
    )
    return {"trace": append_trace(state.get("trace"), event)}


async def _diagnose_query(state: AgentGraphState, session: Session | None = None) -> dict:
    started_at = start_trace()
    evidence_id = _state_evidence_id(state) or f"ev_{uuid4().hex[:12]}"
    logger.info("agent.stage stage=diagnose_query status=started evidence_id=%s", evidence_id)
    body = state.get("chat_request")
    if body is None:
        # 详情路径不需要普通搜索诊断；保留占位诊断是为了让 graph state 结构稳定。
        event = finish_trace(
            "diagnose_query",
            started_at,
            "Detail request does not require query diagnosis.",
            evidence_id=evidence_id,
        )
        return {
            "query_diagnosis": {
                "intent": "detail",
                "confidence": 0.8,
                "missing_slots": [],
                "known_slots": {},
                "should_clarify": False,
                "clarifying_question": None,
            },
            "trace": append_trace(state.get("trace"), event),
        }
    update = await diagnose_query_stage(
        session,
        request=body,
        fastapi_request=state["fastapi_request"],
        active_constraints=state.get("active_constraints", {}),
        last_query_context=state.get("last_query_context", {}),
        shown_mod_titles=state.get("shown_mod_titles", []),
        evidence_id=evidence_id,
    )
    evidence_id = str(update.get("evidence_id") or evidence_id)
    event = finish_trace("diagnose_query", started_at, "Agent query diagnosed.", evidence_id=evidence_id)
    logger.info(
        "agent.stage stage=diagnose_query status=succeeded duration_ms=%s evidence_id=%s",
        _event_duration_ms(event),
        evidence_id,
    )
    return {
        **update,
        "trace": append_trace(state.get("trace"), event),
    }


def _plan_tools(state: AgentGraphState) -> dict:
    started_at = start_trace()
    evidence_id = _state_evidence_id(state)
    logger.info("agent.stage stage=plan_tools status=started evidence_id=%s", evidence_id)
    # 工具计划根据诊断结果和偏好选择允许的检索工具；硬约束仍由后续 tool 校验。
    tool_plan = ToolPlannerTool().run(
        ToolPlannerInput(
            query_diagnosis=state.get("query_diagnosis") or {},
            preferences=state.get("preferences") or {},
            local_only=False,
            evidence_id=evidence_id,
        )
    )
    event = finish_trace("plan_tools", started_at, "Agent retrieval tools planned.", evidence_id=evidence_id)
    logger.info(
        "agent.stage stage=plan_tools status=succeeded duration_ms=%s evidence_id=%s",
        _event_duration_ms(event),
        evidence_id,
    )
    return {
        "tool_plan": tool_plan,
        "query_plan": dict(state.get("query_plan") or {}),
        "trace": append_trace(state.get("trace"), event),
    }


async def _staged_retrieval(state: AgentGraphState, session: Session | None = None) -> dict:
    started_at = start_trace()
    evidence_id = _state_evidence_id(state)
    logger.info("agent.stage stage=staged_retrieval status=started evidence_id=%s", evidence_id)
    if session is None:
        raise RuntimeError("session is required for staged retrieval")
    # 检索阶段只返回标准 SearchResult 和 evidence，不直接决定最终前端展示顺序。
    update = await execute_retrieval_stage(
        session,
        query=_state_query(state),
        query_plan=state.get("query_plan") or {},
        tool_plan=state.get("tool_plan") or {},
        evidence_id=evidence_id,
    )
    event = finish_trace("staged_retrieval", started_at, "Agent retrieval tools executed.", evidence_id=evidence_id)
    logger.info(
        "agent.stage stage=staged_retrieval status=succeeded duration_ms=%s staged=%s online=%s evidence_id=%s",
        _event_duration_ms(event),
        len(update.get("staged_results") or []),
        len(update.get("online_results") or []),
        evidence_id,
    )
    return {
        **update,
        "trace": append_trace(state.get("trace"), event),
    }


async def _rank_results(state: AgentGraphState, session: Session | None = None) -> dict:
    started_at = start_trace()
    evidence_id = _state_evidence_id(state)
    logger.info("agent.stage stage=rank_results status=started evidence_id=%s", evidence_id)
    if session is None:
        raise RuntimeError("session is required for ranking")
    # 排序阶段负责融合、本地物化、LLM 候选校验和空结果恢复。
    update = await rank_candidates_stage(
        session,
        query=_state_query(state),
        query_plan=state.get("query_plan") or {},
        staged_results=state.get("staged_results") or [],
        online_results=state.get("online_results") or [],
        retrieval_evidence=state.get("retrieval_evidence") or [],
        llm=_state_llm_config(state),
        evidence_id=evidence_id,
    )
    event = finish_trace("rank_results", started_at, "Agent candidates ranked and materialized.", evidence_id=evidence_id)
    logger.info(
        "agent.stage stage=rank_results status=succeeded duration_ms=%s matches=%s evidence_id=%s",
        _event_duration_ms(event),
        len(update.get("matches") or []),
        evidence_id,
    )
    return {
        **update,
        "trace": append_trace(state.get("trace"), event),
    }


async def _generate_answer(state: AgentGraphState) -> dict:
    started_at = start_trace()
    evidence_id = _state_evidence_id(state)
    logger.info("agent.stage stage=generate_answer status=started evidence_id=%s", evidence_id)
    body = state.get("chat_request")
    if body is None:
        # 详情回答已经在 generate_detail_answer 节点生成，这里只补 trace。
        return {"trace": append_trace(state.get("trace"), finish_trace("generate_answer", started_at, "Detail response already generated.", evidence_id=evidence_id))}
    update = await generate_chat_answer_stage(
        query=body.message.strip(),
        query_plan=state.get("query_plan") or {},
        matches=state.get("matches") or [],
        retrieval_evidence=state.get("retrieval_evidence") or [],
        history=body.history,
        llm=_state_llm_config(state),
        evidence_id=evidence_id,
    )
    event = finish_trace("generate_answer", started_at, "Agent answer generated.", evidence_id=evidence_id)
    answer_summary = update.get("answer_summary") if isinstance(update.get("answer_summary"), dict) else {}
    logger.info(
        "agent.stage stage=generate_answer status=succeeded duration_ms=%s matches=%s used_llm=%s evidence_id=%s",
        _event_duration_ms(event),
        answer_summary.get("match_count", 0),
        bool(answer_summary.get("used_llm")),
        evidence_id,
    )
    return {
        "response": update.get("response"),
        "trace": append_trace(state.get("trace"), event),
    }


def _reflect(state: AgentGraphState) -> dict:
    started_at = start_trace()
    evidence_id = _state_evidence_id(state)
    logger.info("agent.stage stage=reflect status=started evidence_id=%s", evidence_id)
    notes = [
        *state.get("reflection_notes", []),
        {
            "stage": "graph",
            "public_summary": "已完成上下文、诊断、工具计划、检索和排序兼容节点。",
        },
    ]
    event = finish_trace("reflect", started_at, "Graph compatibility reflection recorded.", evidence_id=evidence_id)
    logger.info(
        "agent.stage stage=reflect status=succeeded duration_ms=%s evidence_id=%s",
        _event_duration_ms(event),
        evidence_id,
    )
    return {
        "reflection_notes": notes,
        "trace": append_trace(state.get("trace"), event),
    }


async def generate_detail_answer_step(session: Session, state: AgentGraphState) -> dict:
    started_at = start_trace()
    evidence_id = _state_evidence_id(state)
    logger.info("agent.stage stage=generate_detail_answer status=started evidence_id=%s", evidence_id)
    try:
        update = await _generate_detail_answer(session, state)
    except Exception as exc:
        logger.info(
            "agent.stage stage=generate_detail_answer status=failed error_type=%s evidence_id=%s",
            type(exc).__name__,
            evidence_id,
        )
        return {
            "trace": append_trace(
                state.get("trace"),
                fail_trace("generate_detail_answer", started_at, exc, evidence_id=evidence_id),
            ),
            "errors": [*state.get("errors", []), type(exc).__name__],
        }
    event = finish_trace("generate_detail_answer", started_at, "Mod detail answer generated.", evidence_id=evidence_id)
    logger.info(
        "agent.stage stage=generate_detail_answer status=succeeded duration_ms=%s evidence_id=%s",
        _event_duration_ms(event),
        evidence_id,
    )
    return {
        **update,
        "trace": append_trace(state.get("trace"), event),
    }


async def _generate_detail_answer(session: Session, state: AgentGraphState) -> dict:
    return await generate_detail_answer_stage(
        session,
        request_kind=state["request_kind"],
        detail_request=state.get("detail_request"),
        fastapi_request=state["fastapi_request"],
    )


def _state_evidence_id(state: AgentGraphState) -> str:
    direct = str(state.get("evidence_id") or "").strip()
    if direct:
        return direct
    query_plan = state.get("query_plan")
    if isinstance(query_plan, dict):
        return str(query_plan.get("evidence_id") or "").strip()
    return ""


def _state_query(state: AgentGraphState) -> str:
    body = state.get("chat_request")
    if body is not None:
        return body.message.strip()
    detail = state.get("detail_request")
    if detail is not None:
        return (detail.question or "").strip()
    return ""


def _state_llm_config(state: AgentGraphState) -> dict[str, object]:
    return {
        "available": bool(state.get("llm_available")),
        "provider": str(state.get("llm_provider") or ""),
        "api_key": str(state.get("llm_api_key") or ""),
        "base_url": str(state.get("llm_base_url") or ""),
        "model": str(state.get("llm_model") or ""),
    }


def build_agent_graph(session: Session):
    def route_after_context(state: AgentGraphState) -> str:
        # 两条路径共享上下文摘要：普通 chat 继续诊断检索，详情请求直接生成详情回答。
        if state.get("request_kind") == "mod_detail":
            return "generate_detail_answer"
        return "diagnose_query"

    async def diagnose_query(state: AgentGraphState) -> dict:
        return await _diagnose_query(state, session)

    async def staged_retrieval(state: AgentGraphState) -> dict:
        return await _staged_retrieval(state, session)

    async def rank_results(state: AgentGraphState) -> dict:
        return await _rank_results(state, session)

    async def generate_detail_answer(state: AgentGraphState) -> dict:
        started_at = start_trace()
        evidence_id = _state_evidence_id(state)
        try:
            update = await _generate_detail_answer(session, state)
        except Exception:
            # 这里故意保留异常向 API 调用方传播；兼容旧行为比记录失败 trace 更重要。
            raise
        return {
            **update,
            "trace": append_trace(
                state.get("trace"),
                finish_trace(
                    "generate_detail_answer",
                    started_at,
                    "Mod detail answer generated.",
                    evidence_id=evidence_id,
                ),
            ),
        }

    graph = StateGraph(AgentGraphState)
    graph.add_node("load_state", _load_state)
    graph.add_node("summarize_context", _summarize_context)
    graph.add_node("diagnose_query", diagnose_query)
    graph.add_node("plan_tools", _plan_tools)
    graph.add_node("staged_retrieval", staged_retrieval)
    graph.add_node("rank_results", rank_results)
    graph.add_node("generate_answer", _generate_answer)
    graph.add_node("reflect", _reflect)
    graph.add_node("generate_detail_answer", generate_detail_answer)
    graph.add_node("persist_result", _persist_result)
    graph.add_edge(START, "load_state")
    graph.add_edge("load_state", "summarize_context")
    graph.add_conditional_edges(
        "summarize_context",
        route_after_context,
        {
            "diagnose_query": "diagnose_query",
            "generate_detail_answer": "generate_detail_answer",
        },
    )
    graph.add_edge("diagnose_query", "plan_tools")
    graph.add_edge("plan_tools", "staged_retrieval")
    graph.add_edge("staged_retrieval", "rank_results")
    graph.add_edge("rank_results", "generate_answer")
    graph.add_edge("generate_answer", "reflect")
    graph.add_edge("reflect", "persist_result")
    graph.add_edge("generate_detail_answer", "persist_result")
    graph.add_edge("persist_result", END)
    return graph.compile()


async def run_agent_graph(session: Session, state: AgentGraphState) -> AgentGraphState:
    started_at = start_trace()
    request_kind = state.get("request_kind", "unknown")
    logger.info("agent.workflow graph=mod_search request_kind=%s status=started", request_kind)
    graph = build_agent_graph(session)
    try:
        result = await graph.ainvoke(state)
    except Exception as exc:
        logger.info(
            "agent.workflow graph=mod_search request_kind=%s status=failed duration_ms=%s error_type=%s",
            request_kind,
            elapsed_ms(started_at),
            type(exc).__name__,
        )
        raise
    logger.info(
        "agent.workflow graph=mod_search request_kind=%s status=succeeded duration_ms=%s trace_steps=%s errors=%s",
        request_kind,
        elapsed_ms(started_at),
        len(result.get("trace") or []),
        len(result.get("errors") or []),
    )
    return result

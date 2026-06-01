import logging
import re
from uuid import uuid4

from fastapi import Request
from sqlalchemy import func
from sqlmodel import Session, select

from app.models.mod import Mod
from app.services.agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentModDetailRequest,
)
from app.services.agent.tools.chat_request_guard_tool import (
    ChatRequestGuardInput,
    ChatRequestGuardTool,
)
from app.services.agent.tracing.search_trace import TraceEvent, elapsed_ms, start_trace
from app.services.agent.workflows.mod_search_graph import run_agent_graph
from app.services.agent.workflows.response_finalization import finalize_chat_response

logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(self, session: Session):
        """请求级 Agent 运行时，只持有本轮数据库会话和最近一次 graph trace。"""
        self.session = session
        self.last_trace: list[TraceEvent] = []

    async def chat(self, body: AgentChatRequest, request: Request) -> AgentChatResponse:
        # 用户用普通 chat 问“详细解析某个 MOD”时，优先复用详情问答链路，
        # 避免先做泛搜索再从结果里猜目标。
        detail_mod_id = _resolve_detail_mod_id_from_chat(self.session, body.message)
        if detail_mod_id is not None:
            return await self.ask_mod_detail(
                AgentModDetailRequest(
                    mod_id=detail_mod_id,
                    question=body.message,
                    history=body.history,
                    provider_override=body.provider_override,
                    model_override=body.model_override,
                ),
                request,
            )

        evidence_id = _new_evidence_id()
        # guard 只处理请求级短路场景；真正的理解、检索和回答仍由 graph 执行。
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
        # 普通 chat 的 memory evidence、audit 和一致性保护在 graph 外收尾，
        # 这样 graph 节点只负责编排和产出候选响应。
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
        # 详情问答补齐与普通 chat 一致的返回契约：evidence/memory/audit 等字段。
        return finalize_chat_response(
            self.session,
            request=_to_chat_request(body),
            response=response,
            graph_state=state,
            fallback_evidence_id=evidence_id,
        )

    async def _run_graph(self, request_kind: str, state: dict) -> dict:
        started_at = start_trace()
        logger.info("agent.runtime request_kind=%s status=started", request_kind)
        try:
            result = await run_agent_graph(self.session, state)
        except Exception as exc:
            logger.info(
                "agent.runtime request_kind=%s status=failed duration_ms=%s error_type=%s",
                request_kind,
                elapsed_ms(started_at),
                type(exc).__name__,
            )
            raise
        response = result.get("response")
        trace = result.get("trace") or []
        logger.info(
            "agent.runtime request_kind=%s status=succeeded duration_ms=%s trace_steps=%s matches=%s",
            request_kind,
            elapsed_ms(started_at),
            len(trace),
            len(response.matches) if response is not None else 0,
        )
        return result


def _to_chat_request(detail_request: AgentModDetailRequest) -> AgentChatRequest:
    message = (detail_request.question or "").strip()
    if not message:
        message = "查看 MOD 详情"
    return AgentChatRequest(
        message=message,
        history=list(detail_request.history),
        provider_override=detail_request.provider_override,
        model_override=detail_request.model_override,
    )



def _new_evidence_id() -> str:
    return f"ev_{uuid4().hex[:12]}"


def _resolve_detail_mod_id_from_chat(session: Session, message: str) -> int | None:
    title = _extract_detail_title(message)
    if not title:
        return None
    normalized_title = _normalize_title(title)
    if not normalized_title:
        return None
    # 详情直达只接受标题或中文标题精确命中，避免把模糊搜索误判成指定 MOD。
    statement = (
        select(Mod)
        .where(
            (func.lower(Mod.title) == normalized_title)
            | (func.lower(func.coalesce(Mod.translated_title_zh, "")) == normalized_title)
        )
        .order_by(Mod.ignored.asc(), Mod.id.desc())
        .limit(1)
    )
    mod = session.exec(statement).first()
    return mod.id if mod and mod.id is not None else None


def _extract_detail_title(message: str) -> str:
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if not re.search(r"(详细解析|详细介绍|详情|分析)", text, flags=re.IGNORECASE):
        return ""
    match = re.search(r"(?:这个\s*)?mod\s*[：:]\s*(.+)$", text, flags=re.IGNORECASE)
    if match:
        return _strip_wrapping_punctuation(match.group(1))
    match = re.search(r"(?:详细解析|详细介绍|分析)\s+(?:这个\s*)?(?:mod\s*)?(.+)$", text, flags=re.IGNORECASE)
    if match:
        return _strip_wrapping_punctuation(match.group(1))
    return ""


def _strip_wrapping_punctuation(value: str) -> str:
    return str(value or "").strip().strip(" \t\r\n\"'“”‘’`。，.：:")


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()

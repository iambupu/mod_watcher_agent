import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.db import get_session
from app.services.agent import conversation_service as conversations
from app.services.agent.chat_service import AgentService
from app.services.agent.llm_config_service import (
    InvalidLlmProviderOverrideError,
    get_llm_config,
)
from app.services.agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentConversationNewResponse,
    AgentConversationState,
    AgentConversationStateSaveRequest,
    AgentModDetailRequest,
)
from app.services.agent.tracing.search_trace import elapsed_ms, start_trace
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/agent", tags=["agent"])
SessionDep = Annotated[Session, Depends(get_session)]
logger = logging.getLogger(__name__)


def _validate_provider_override(session: Session, provider_override: str | None) -> None:
    if not (provider_override or "").strip():
        return
    try:
        get_llm_config(
            SettingsService(session),
            provider_override=provider_override,
        )
    except InvalidLlmProviderOverrideError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/chat", response_model=AgentChatResponse)
async def chat_with_agent(
    body: AgentChatRequest,
    request: Request,
    session: SessionDep,
):
    """处理 Agent 普通对话请求，并记录接口级耗时与命中数量。"""
    _validate_provider_override(session, body.provider_override)
    started_at = start_trace()
    logger.info(
        "agent.api path=/api/agent/chat status=started history=%s provider_override=%s model_override=%s",
        len(body.history),
        bool(body.provider_override),
        bool(body.model_override),
    )
    try:
        response = await AgentService(session).chat(body, request)
    except Exception as exc:
        logger.info(
            "agent.api path=/api/agent/chat status=failed duration_ms=%s error_type=%s",
            elapsed_ms(started_at),
            type(exc).__name__,
        )
        raise
    logger.info(
        "agent.api path=/api/agent/chat status=succeeded duration_ms=%s matches=%s used_llm=%s",
        elapsed_ms(started_at),
        len(response.matches),
        response.used_llm,
    )
    return response


@router.post("/mod-detail", response_model=AgentChatResponse)
async def ask_mod_detail(
    body: AgentModDetailRequest,
    request: Request,
    session: SessionDep,
):
    """处理针对单个 Mod 的详情追问。"""
    _validate_provider_override(session, body.provider_override)
    return await AgentService(session).ask_mod_detail(body, request)

@router.get("/conversation-state", response_model=AgentConversationState)
async def get_conversation_state(
    session: SessionDep,
):
    """读取前端 AgentChat 需要恢复的会话状态。"""
    settings = SettingsService(session)
    return conversations.load_conversation_state(session, settings)


@router.post("/conversation-state", response_model=AgentConversationState)
async def save_conversation_state(
    body: AgentConversationStateSaveRequest,
    session: SessionDep,
):
    """保存 AgentChat 会话快照，并返回服务端确认后的最新状态。"""
    settings = SettingsService(session)
    return conversations.save_conversation_state(body=body, session=session, settings=settings)


@router.post("/conversation/new", response_model=AgentConversationNewResponse)
async def start_new_conversation(
    session: SessionDep,
):
    """创建一个新的 AgentChat 会话并切换为活动会话。"""
    settings = SettingsService(session)
    session_id = conversations.start_new_conversation(settings)
    return AgentConversationNewResponse(session_id=session_id)

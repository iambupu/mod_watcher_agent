import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from app.db import get_session
from app.services.agent import conversation_service as conversations
from app.services.agent.chat_service import AgentService
from app.services.agent.runtime import AgentRuntime
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


@router.post("/chat", response_model=AgentChatResponse)
async def chat_with_agent(
    body: AgentChatRequest,
    request: Request,
    session: SessionDep,
):
    """处理当前模块的业务逻辑并返回结果。"""
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
    """处理当前模块的业务逻辑并返回结果。"""
    return await AgentRuntime(session).ask_mod_detail(body, request)

@router.get("/conversation-state", response_model=AgentConversationState)
async def get_conversation_state(
    session: SessionDep,
):
    """读取并返回对应的数据。"""
    settings = SettingsService(session)
    return conversations.load_conversation_state(session, settings)


@router.post("/conversation-state", response_model=AgentConversationState)
async def save_conversation_state(
    body: AgentConversationStateSaveRequest,
    session: SessionDep,
):
    """保存数据并返回最新状态。"""
    settings = SettingsService(session)
    return conversations.save_conversation_state(body=body, session=session, settings=settings)


@router.post("/conversation/new", response_model=AgentConversationNewResponse)
async def start_new_conversation(
    session: SessionDep,
):
    """处理当前模块的业务逻辑并返回结果。"""
    settings = SettingsService(session)
    session_id = conversations.start_new_conversation(settings)
    return AgentConversationNewResponse(session_id=session_id)

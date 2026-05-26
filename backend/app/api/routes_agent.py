import logging
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from app.db import get_session
from app.services.agent import conversation_service as conversations
from app.services.agent.chat_service import AgentService
from app.services.agent.history import compress_history
from app.services.agent.llm_config_service import get_llm_config
from app.services.agent.mod_search_service import apply_query_plan, query_mods_with_plan
from app.services.agent.query_planner import normalize_query_plan
from app.services.agent.response_builder import build_response_cards
from app.services.agent.runtime import AgentRuntime
from app.services.agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentConversationNewResponse,
    AgentConversationState,
    AgentConversationStateSaveRequest,
    AgentModDetailRequest,
)
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/agent", tags=["agent"])
SessionDep = Annotated[Session, Depends(get_session)]
logger = logging.getLogger(__name__)

# Backward-compatible names for existing tests and internal imports.
_apply_query_plan = apply_query_plan
_build_response_cards = build_response_cards
_compress_history = compress_history
_get_llm_config = get_llm_config
_load_conversation_state = conversations.load_conversation_state
_normalize_query_plan = normalize_query_plan
_query_mods_with_plan = query_mods_with_plan


@router.post("/chat", response_model=AgentChatResponse)
async def chat_with_agent(
    body: AgentChatRequest,
    request: Request,
    session: SessionDep,
):
    """处理当前模块的业务逻辑并返回结果。"""
    started_at = perf_counter()
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
            _elapsed_ms(started_at),
            type(exc).__name__,
        )
        raise
    logger.info(
        "agent.api path=/api/agent/chat status=succeeded duration_ms=%s matches=%s used_llm=%s",
        _elapsed_ms(started_at),
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


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


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

import logging
from dataclasses import dataclass

from app.services.agent.response_builder import build_status_response_cards
from app.services.agent.schemas import AgentChatRequest, AgentChatResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatRequestGuardInput:
    request: AgentChatRequest
    evidence_id: str = ""


@dataclass(frozen=True)
class ChatRequestGuardOutput:
    response: AgentChatResponse | None


class ChatRequestGuardTool:
    """Agent tool for request-level guard responses before graph execution."""

    name = "chat_request_guard"

    def run(self, tool_input: ChatRequestGuardInput) -> ChatRequestGuardOutput:
        if tool_input.request.message.strip():
            logger.info(
                "agent.tool name=chat_request_guard status=passed evidence_id=%s",
                tool_input.evidence_id,
            )
            return ChatRequestGuardOutput(response=None)
        response = AgentChatResponse(
            answer="请输入要查询的内容。",
            used_llm=False,
            matches=[],
            response_cards=build_status_response_cards(
                analysis="任务分析：当前输入为空，无法识别 Mod 查询意图。",
                evidence="证据：请求消息去除空白后为空。",
                conclusion="结论：需要先提供查询内容。",
                understanding="请先输入你的查询需求。",
                result="当前没有可用结果。",
                next_step="例如：最近更新的 Stellar Blade 画面 Mod。",
            ),
            evidence_id=tool_input.evidence_id or None,
        )
        logger.info(
            "agent.tool name=chat_request_guard status=blocked reason=empty_query evidence_id=%s",
            tool_input.evidence_id,
        )
        return ChatRequestGuardOutput(response=response)

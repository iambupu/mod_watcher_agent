from fastapi import Request
from sqlmodel import Session

from app.services.agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentModDetailRequest,
)


class AgentService:
    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session

    async def chat(
        self,
        body: AgentChatRequest,
        request: Request,
    ) -> AgentChatResponse:
        """通过 runtime graph 入口执行普通聊天请求。"""
        from app.services.agent.runtime import AgentRuntime

        return await AgentRuntime(self.session).chat(body, request)

    async def ask_mod_detail(self, body: AgentModDetailRequest, request: Request) -> AgentChatResponse:
        """通过 runtime graph 入口执行指定 MOD 的详情问答。"""
        from app.services.agent.runtime import AgentRuntime

        return await AgentRuntime(self.session).ask_mod_detail(body, request)

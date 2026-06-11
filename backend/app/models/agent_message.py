# 中文注释：定义Agent 会话消息相关的数据库持久化模型。

from sqlmodel import Field, SQLModel


class AgentMessage(SQLModel, table=True):
    __tablename__ = "agent_messages"

    id: int | None = Field(default=None, primary_key=True)
    message_id: str = Field(max_length=64, index=True)
    role: str = Field(max_length=16)
    text: str
    session_id: str = Field(max_length=64, index=True)
    created_at: str
    matches_json: str | None = Field(default=None)
    response_cards_json: str | None = Field(default=None)
    audit_json: str | None = Field(default=None)
    llm_provider: str | None = Field(default=None, max_length=64)
    llm_model: str | None = Field(default=None, max_length=128)
    sort_index: int = Field(default=0, index=True)

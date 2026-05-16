from typing import Optional

from sqlmodel import Field, SQLModel


class AgentMessage(SQLModel, table=True):
    __tablename__ = "agent_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: str = Field(max_length=64, index=True)
    role: str = Field(max_length=16)
    text: str
    session_id: str = Field(max_length=64, index=True)
    created_at: str
    matches_json: Optional[str] = Field(default=None)
    sort_index: int = Field(default=0, index=True)

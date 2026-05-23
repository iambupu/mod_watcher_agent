from typing import Literal

from pydantic import BaseModel, Field


class AgentHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[AgentHistoryItem] = []
    provider_override: str | None = Field(default=None, max_length=64)
    model_override: str | None = Field(default=None, max_length=128)


class AgentModDetailRequest(BaseModel):
    mod_id: int
    question: str | None = Field(default=None, max_length=4000)
    history: list[AgentHistoryItem] = []
    provider_override: str | None = Field(default=None, max_length=64)
    model_override: str | None = Field(default=None, max_length=128)


class AgentModMatch(BaseModel):
    id: int
    title: str
    source: str
    game: str
    game_domain: str | None = None
    category: str | None = None
    author: str | None
    version: str | None
    url: str
    updated_at_remote: str | None
    downloads: int | None = None
    endorsements: int | None = None
    likes: int | None = None
    adult_content: bool | None = None
    score: int
    original_summary: str | None = None
    translated_summary: str | None = None


class AgentChatResponse(BaseModel):
    answer: str
    used_llm: bool
    matches: list[AgentModMatch]
    response_cards: dict[str, list[str]] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


class AgentConversationMessage(BaseModel):
    id: str
    role: Literal["user", "assistant", "separator"]
    text: str
    session_id: str
    created_at: str | None = None
    matches: list[AgentModMatch] | None = None
    response_cards: dict[str, list[str]] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


class AgentConversationState(BaseModel):
    messages: list[AgentConversationMessage]
    active_session_id: str


class AgentConversationStateSaveRequest(BaseModel):
    messages: list[AgentConversationMessage]
    active_session_id: str
    client_updated_at: str | None = None


class AgentConversationNewResponse(BaseModel):
    session_id: str

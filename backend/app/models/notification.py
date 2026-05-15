from typing import Optional
from sqlmodel import SQLModel, Field


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    channel: str = Field(max_length=32)
    recipient: str = Field(max_length=255)
    subject: str = Field(max_length=512)
    body: str
    status: str = Field(default="pending", max_length=32)
    error_message: Optional[str] = Field(default=None)
    sent_at: Optional[str] = Field(default=None)
    created_at: str

from typing import Optional
from sqlmodel import SQLModel, Field


class SystemNotificationEvent(SQLModel, table=True):
    __tablename__ = "system_notifications"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str = Field(max_length=50)
    title: str = Field(max_length=512)
    message: str
    mod_id: Optional[int] = Field(default=None)
    related_url: Optional[str] = Field(default=None)
    seen: bool = Field(default=False)
    created_at: str

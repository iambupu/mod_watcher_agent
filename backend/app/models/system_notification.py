
from sqlmodel import Field, SQLModel


class SystemNotificationEvent(SQLModel, table=True):
    __tablename__ = "system_notifications"
    __table_args__ = {"sqlite_autoincrement": True}

    id: int | None = Field(default=None, primary_key=True)
    event_type: str = Field(max_length=50)
    title: str = Field(max_length=512)
    message: str
    mod_id: int | None = Field(default=None)
    related_url: str | None = Field(default=None)
    seen: bool = Field(default=False)
    created_at: str

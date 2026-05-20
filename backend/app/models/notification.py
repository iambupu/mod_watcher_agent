
from sqlmodel import Field, SQLModel


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    __table_args__ = {"sqlite_autoincrement": True}

    id: int | None = Field(default=None, primary_key=True)
    channel: str = Field(max_length=32)
    recipient: str = Field(max_length=255)
    subject: str = Field(max_length=512)
    body: str
    status: str = Field(default="pending", max_length=32)
    error_message: str | None = Field(default=None)
    sent_at: str | None = Field(default=None)
    read: bool = Field(default=False)
    created_at: str

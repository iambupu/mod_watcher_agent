
from sqlmodel import Field, SQLModel


class ModSummary(SQLModel, table=True):
    __tablename__ = "mod_summaries"
    __table_args__ = {"sqlite_autoincrement": True}

    id: int | None = Field(default=None, primary_key=True)
    mod_id: int = Field(foreign_key="mods.id")
    language: str = Field(max_length=10)
    summary_type: str = Field(max_length=32)
    content: str
    model: str | None = Field(default=None, max_length=64)
    generated_at: str

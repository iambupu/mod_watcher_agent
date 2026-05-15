from typing import Optional
from sqlmodel import SQLModel, Field


class JobRun(SQLModel, table=True):
    __tablename__ = "job_runs"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    job_name: str = Field(max_length=255)
    status: str = Field(max_length=32)
    started_at: str
    finished_at: Optional[str] = Field(default=None)
    items_scanned: int = Field(default=0)
    items_matched: int = Field(default=0)
    error_message: Optional[str] = Field(default=None)
    metadata_json: Optional[str] = Field(default=None)

# 中文注释：定义设置项相关的数据库持久化模型。

from sqlmodel import Field, SQLModel


class Setting(SQLModel, table=True):
    __tablename__ = "settings"
    __table_args__ = {"sqlite_autoincrement": True}

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(max_length=255, unique=True)
    value: str
    updated_at: str

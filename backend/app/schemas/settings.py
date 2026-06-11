# 中文注释：定义设置 API请求和响应的数据契约。

from pydantic import BaseModel


class SettingsRead(BaseModel):
    settings: dict[str, str]


class SettingsUpdate(BaseModel):
    settings: dict[str, str | None]

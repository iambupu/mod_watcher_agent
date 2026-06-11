# 中文注释：封装 Agent 服务层的Agent 筛选值规范化逻辑。

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.utils.numeric import optional_bounded_int, optional_nonnegative_int


def url_without_query(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def optional_min_metric(value: Any) -> int | None:
    return optional_nonnegative_int(value)


def optional_time_window(value: Any) -> int | None:
    return optional_bounded_int(value, minimum=1, maximum=365)

import re

from app.services.agent.semantic_search import strip_scope


def infer_numeric_constraints(query: str) -> dict[str, int]:
    """从自然语言搜索请求中推断数值阈值过滤条件。"""
    text = strip_scope(query)
    constraints: dict[str, int] = {}
    for field, metric_patterns in {
        "min_downloads": [
            r"(?:下载量|下载|downloads?)\s*(?:至少|不少于|不低于|超过|大于|>=|>|以上|more than|over|at least|min(?:imum)?)\s*([0-9][0-9,]*)",
            r"([0-9][0-9,]*)\s*\+?\s*(?:以上)?\s*(?:下载量|下载|downloads?)",
        ],
        "min_endorsements": [
            r"(?:背书|点赞|endorsements?)\s*(?:至少|不少于|不低于|超过|大于|>=|>|以上|more than|over|at least|min(?:imum)?)\s*([0-9][0-9,]*)",
            r"([0-9][0-9,]*)\s*\+?\s*(?:以上)?\s*(?:背书|点赞|endorsements?)",
        ],
        "min_views": [
            r"(?:浏览量|浏览|views?)\s*(?:至少|不少于|不低于|超过|大于|>=|>|以上|more than|over|at least|min(?:imum)?)\s*([0-9][0-9,]*)",
            r"([0-9][0-9,]*)\s*\+?\s*(?:以上)?\s*(?:浏览量|浏览|views?)",
        ],
        "min_likes": [
            r"(?:喜欢数|喜欢|likes?)\s*(?:至少|不少于|不低于|超过|大于|>=|>|以上|more than|over|at least|min(?:imum)?)\s*([0-9][0-9,]*)",
            r"([0-9][0-9,]*)\s*\+?\s*(?:以上)?\s*(?:喜欢数|喜欢|likes?)",
        ],
    }.items():
        value = _first_positive_int(text, metric_patterns)
        if value is not None:
            constraints[field] = value
    return constraints


def query_without_metric_terms(query: str) -> str:
    cleaned = query
    metric_words = (
        r"下载量|下载|downloads?|背书|点赞|endorsements?|浏览量|浏览|views?|喜欢数|喜欢|likes?"
    )
    threshold_words = (
        r"至少|不少于|不低于|超过|大于|>=|>|以上|more than|over|at least|min(?:imum)?"
    )
    for pattern in [
        rf"(?:{metric_words})\s*(?:{threshold_words})\s*[0-9][0-9,]*",
        rf"[0-9][0-9,]*\s*\+?\s*(?:以上)?\s*(?:{metric_words})",
    ]:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def infer_time_window(query: str) -> dict[str, int]:
    """推断“最近 7 天”或“last 2 weeks”等显式时间窗口。"""
    text = strip_scope(query)
    lower_text = text.lower()
    patterns = [
        r"(?:最近|近|过去|过去的)\s*([0-9一二两三四五六七八九十]+)\s*(天|日|周|星期|个月|月)",
        r"\b(?:last|past|within)\s+([0-9]+)\s+(day|days|week|weeks|month|months)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower_text, flags=re.IGNORECASE)
        if not match:
            continue
        amount = _parse_small_int(match.group(1))
        unit = match.group(2)
        days = _time_window_days(amount, unit)
        if days is not None:
            return {"updated_since_days": days}
    fixed_windows = [
        (["最近一周", "近一周", "过去一周", "last week", "past week"], 7),
        (["最近两周", "近两周", "过去两周", "last two weeks", "past two weeks"], 14),
        (["最近一个月", "近一个月", "过去一个月", "last month", "past month"], 30),
    ]
    for markers, days in fixed_windows:
        if any(marker in lower_text for marker in markers):
            return {"updated_since_days": days}
    return {}


def infer_absolute_date_constraints(query: str) -> dict[str, str]:
    """推断“2024 后更新”等绝对日期或年份范围过滤条件。"""
    text = strip_scope(query)
    lower_text = text.lower()
    field = _date_field_from_text(lower_text)
    constraints: dict[str, str] = {}
    patterns = [
        (r"(\d{4}(?:-\d{1,2}-\d{1,2})?)\s*(?:之后|以后|以来|后)", "after"),
        (r"(?:after|since)\s+(\d{4}(?:-\d{1,2}-\d{1,2})?)", "after"),
        (r"(\d{4}(?:-\d{1,2}-\d{1,2})?)\s*(?:之前|以前|前)", "before"),
        (r"(?:before|until)\s+(\d{4}(?:-\d{1,2}-\d{1,2})?)", "before"),
        (r"(\d{4})\s*年\s*(?:之后|以后|以来|后)", "after"),
        (r"(\d{4})\s*年\s*(?:之前|以前|前)", "before"),
    ]
    for pattern, direction in patterns:
        match = re.search(pattern, lower_text, flags=re.IGNORECASE)
        if not match:
            continue
        value = _absolute_date_boundary(match.group(1), direction)
        if value:
            constraints[f"{field}_{direction}"] = value
    year_range = _absolute_year_range(lower_text)
    if year_range:
        after_value, before_value = year_range
        constraints.setdefault(f"{field}_after", after_value)
        constraints.setdefault(f"{field}_before", before_value)
    return constraints


def query_without_absolute_date_terms(query: str) -> str:
    cleaned = query
    for pattern in [
        r"\d{4}(?:-\d{1,2}-\d{1,2})?\s*(?:之后|以后|以来|前|之前|以前)",
        r"\d{4}\s*年\s*(?:之后|以后|以来|前|之前|以前)",
        r"\d{4}\s*年\s*(?:更新|发布|创建)",
        r"\b(?:updated?|published?|created?)\s+(?:in|during)\s+\d{4}\b",
        r"\b(?:after|since|before|until)\s+\d{4}(?:-\d{1,2}-\d{1,2})?\b",
        r"(?:更新|发布|创建|updated?|published?|created?)",
    ]:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _first_positive_int(text: str, patterns: list[str]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1).replace(",", "")
        try:
            value = int(raw)
        except ValueError:
            continue
        if value >= 0:
            return value
    return None


def _parse_small_int(raw: str) -> int | None:
    value = str(raw or "").strip().lower()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    chinese_digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if value in chinese_digits:
        return chinese_digits[value]
    if value.startswith("十") and len(value) == 2 and value[1] in chinese_digits:
        return 10 + chinese_digits[value[1]]
    if value.endswith("十") and len(value) == 2 and value[0] in chinese_digits:
        return chinese_digits[value[0]] * 10
    if "十" in value:
        left, _, right = value.partition("十")
        if left in chinese_digits and right in chinese_digits:
            return chinese_digits[left] * 10 + chinese_digits[right]
    return None


def _time_window_days(amount: int | None, unit: str) -> int | None:
    if amount is None or amount <= 0:
        return None
    normalized_unit = str(unit or "").lower()
    if normalized_unit in {"天", "日", "day", "days"}:
        days = amount
    elif normalized_unit in {"周", "星期", "week", "weeks"}:
        days = amount * 7
    elif normalized_unit in {"个月", "月", "month", "months"}:
        days = amount * 30
    else:
        return None
    return max(1, min(365, days))


def _date_field_from_text(text: str) -> str:
    if any(marker in text for marker in ["发布", "published", "publish"]):
        return "published"
    if any(marker in text for marker in ["创建", "created", "create"]):
        return "created"
    return "updated"


def _absolute_date_boundary(raw: str, direction: str) -> str | None:
    value = str(raw or "").strip()
    year_match = re.fullmatch(r"(\d{4})", value)
    if year_match:
        return f"{value}-{'01-01T00:00:00+00:00' if direction == 'after' else '12-31T23:59:59+00:00'}"
    date_match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if not date_match:
        return None
    year, month, day = date_match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}T{'00:00:00' if direction == 'after' else '23:59:59'}+00:00"


def _absolute_year_range(text: str) -> tuple[str, str] | None:
    patterns = [
        r"(\d{4})\s*年\s*(?:更新|发布|创建)",
        r"\b(?:updated?|published?|created?)\s+(?:in|during)\s+(\d{4})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        year = match.group(1)
        return f"{year}-01-01T00:00:00+00:00", f"{year}-12-31T23:59:59+00:00"
    return None

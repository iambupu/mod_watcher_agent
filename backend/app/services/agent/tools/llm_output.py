# 中文注释：封装 Agent 工具层的LLM 输出解析逻辑。

LLM_ERROR_SENTINELS = {
    "error",
    "provider error",
    "llm error",
    "failed to fetch",
    "fetch failed",
    "network error",
    "networkerror when attempting to fetch resource.",
}


def is_empty_or_error_content(content: str) -> bool:
    normalized = str(content or "").strip().lower()
    return not normalized or normalized in LLM_ERROR_SENTINELS

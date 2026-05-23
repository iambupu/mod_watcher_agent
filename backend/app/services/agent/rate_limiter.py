import asyncio
import time

from fastapi import HTTPException, Request

from app.services.agent.conversation_service import AGENT_CHAT_ACTIVE_SESSION_KEY
from app.services.settings_service import SettingsService

AGENT_RATE_LIMIT_CAPACITY = 12.0
AGENT_RATE_LIMIT_REFILL_PER_SEC = 0.2  # 12 tokens/min
AGENT_RATE_LIMIT_BURST = 20.0
AGENT_RATE_BUCKET_TTL_SEC = 300.0
_AGENT_RATE_BUCKETS: dict[str, tuple[float, float]] = {}
_AGENT_RATE_LOCK = asyncio.Lock()


def build_rate_limit_key(request: Request, settings: SettingsService) -> str:
    """构建后续流程需要的数据结构。"""
    active_session = (settings.get(AGENT_CHAT_ACTIVE_SESSION_KEY) or "").strip()
    if active_session:
        return f"agent:{active_session}"
    client_host = request.client.host if request.client else "unknown"
    return f"agent-ip:{client_host}"


async def enforce_rate_limit(key: str) -> None:
    """处理当前模块的业务逻辑并返回结果。"""
    now = time.monotonic()
    async with _AGENT_RATE_LOCK:
        stale_keys = [k for k, (_, last_seen) in _AGENT_RATE_BUCKETS.items() if now - last_seen > AGENT_RATE_BUCKET_TTL_SEC]
        for stale_key in stale_keys:
            _AGENT_RATE_BUCKETS.pop(stale_key, None)
        tokens, last = _AGENT_RATE_BUCKETS.get(key, (AGENT_RATE_LIMIT_CAPACITY, now))
        elapsed = max(0.0, now - last)
        tokens = min(AGENT_RATE_LIMIT_BURST, tokens + elapsed * AGENT_RATE_LIMIT_REFILL_PER_SEC)
        if tokens < 1.0:
            wait_seconds = max(1, int((1.0 - tokens) / AGENT_RATE_LIMIT_REFILL_PER_SEC))
            raise HTTPException(status_code=429, detail=f"请求过于频繁，请在 {wait_seconds}s 后重试。")
        _AGENT_RATE_BUCKETS[key] = (tokens - 1.0, now)

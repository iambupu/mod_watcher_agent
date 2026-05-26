import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

ToolStatus = Literal["succeeded", "failed", "timeout"]


@dataclass(frozen=True)
class ToolExecutionResult:
    status: ToolStatus
    duration_ms: int
    result: Any = None
    error_type: str | None = None
    trace: dict[str, Any] | None = None


async def execute_tool_group(
    tools: dict[str, Callable[[], Awaitable[Any]]],
    *,
    timeout_ms: int,
) -> dict[str, ToolExecutionResult]:
    async def run_one(name: str, fn: Callable[[], Awaitable[Any]]) -> tuple[str, ToolExecutionResult]:
        started = perf_counter()
        try:
            result = await asyncio.wait_for(fn(), timeout=max(timeout_ms, 1) / 1000)
            return name, ToolExecutionResult(
                status="succeeded",
                duration_ms=_elapsed_ms(started),
                result=result,
                trace={"tool": name, "status": "succeeded"},
            )
        except TimeoutError:
            return name, ToolExecutionResult(
                status="timeout",
                duration_ms=_elapsed_ms(started),
                error_type="TimeoutError",
                trace={"tool": name, "status": "timeout"},
            )
        except Exception as exc:
            return name, ToolExecutionResult(
                status="failed",
                duration_ms=_elapsed_ms(started),
                error_type=type(exc).__name__,
                trace={"tool": name, "status": "failed", "error_type": type(exc).__name__},
            )

    pairs = await asyncio.gather(*(run_one(name, fn) for name, fn in tools.items()))
    return dict(pairs)


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))

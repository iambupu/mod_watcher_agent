import logging
from time import perf_counter
from typing import Literal, NotRequired, TypedDict

logger = logging.getLogger(__name__)

TraceStatus = Literal["started", "succeeded", "failed", "skipped"]


class TraceEvent(TypedDict):
    step: str
    status: TraceStatus
    duration_ms: int | None
    evidence_id: NotRequired[str]
    message: NotRequired[str | None]
    error_type: NotRequired[str | None]


def start_trace() -> float:
    return perf_counter()


def elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def finish_trace(
    step: str,
    started_at: float,
    message: str | None = None,
    *,
    evidence_id: str = "",
) -> TraceEvent:
    event: TraceEvent = {
        "step": step,
        "status": "succeeded",
        "duration_ms": elapsed_ms(started_at),
    }
    if evidence_id:
        event["evidence_id"] = evidence_id
    if message is not None:
        event["message"] = message
    return event


def fail_trace(step: str, started_at: float, error: BaseException, *, evidence_id: str = "") -> TraceEvent:
    event: TraceEvent = {
        "step": step,
        "status": "failed",
        "duration_ms": elapsed_ms(started_at),
        "error_type": type(error).__name__,
        "message": "Agent graph step failed.",
    }
    if evidence_id:
        event["evidence_id"] = evidence_id
    return event


def append_trace(trace: list[TraceEvent] | None, event: TraceEvent) -> list[TraceEvent]:
    logger.info(
        "agent.stage step=%s status=%s duration_ms=%s evidence_id=%s message=%s error_type=%s",
        event.get("step"),
        event.get("status"),
        event.get("duration_ms"),
        event.get("evidence_id", ""),
        event.get("message", ""),
        event.get("error_type", ""),
    )
    return [*(trace or []), event]

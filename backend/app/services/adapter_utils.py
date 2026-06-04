"""Adapter helper utilities for safe lifecycle management."""

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.adapters.base import BaseAdapter

T = TypeVar("T")


async def call_with_adapter(
    adapter: BaseAdapter,
    callback: Callable[[BaseAdapter], Awaitable[T]],
    *,
    logger: logging.Logger,
    context: str,
) -> T:
    """Execute a callback with an adapter and always close the adapter afterward."""
    try:
        return await callback(adapter)
    finally:
        try:
            await adapter.aclose()
        except Exception:
            logger.warning(
                "Failed to close adapter during %s",
                context,
                exc_info=True,
            )

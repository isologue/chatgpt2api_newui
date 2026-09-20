from __future__ import annotations

from anyio.to_thread import current_default_thread_limiter

from services.realtime_monitor_service import realtime_monitor_service
from utils.log import logger


def apply_thread_pool_capacity(tokens: int) -> dict[str, int]:
    """Apply the shared AnyIO worker-thread capacity without restarting the app."""
    normalized = max(1, int(tokens))
    limiter = current_default_thread_limiter()
    previous = int(getattr(limiter, "total_tokens", 0) or 0)
    borrowed = int(getattr(limiter, "borrowed_tokens", 0) or 0)
    if previous != normalized:
        limiter.total_tokens = normalized
    realtime_monitor_service.set_threadpool(tokens=normalized, previous_tokens=previous)
    logger.info({
        "event": "runtime_threadpool_configured",
        "previous_tokens": previous,
        "tokens": normalized,
        "borrowed_tokens": borrowed,
    })
    return {
        "tokens": normalized,
        "previous_tokens": previous,
        "borrowed_tokens": borrowed,
    }

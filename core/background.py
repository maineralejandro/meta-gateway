import asyncio
import time

import structlog

from core.security import api_rate_limiter, rate_limiter

logger = structlog.get_logger()

CLEANUP_INTERVAL = 300
PHONE_LOCK_MAX_AGE = 3600
_phone_lock_last_used: dict[str, float] = {}


def touch_phone_lock(phone: str) -> None:
    _phone_lock_last_used[phone] = time.monotonic()


def prune_phone_locks() -> None:
    from core.hitl_router import _phone_locks
    now = time.monotonic()
    stale = [p for p, t in _phone_lock_last_used.items() if now - t > PHONE_LOCK_MAX_AGE]
    for p in stale:
        _phone_locks.pop(p, None)
        _phone_lock_last_used.pop(p, None)
    if stale:
        logger.info("phone_locks_pruned", count=len(stale))


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        try:
            rate_limiter.cleanup()
            api_rate_limiter.cleanup()
            prune_phone_locks()
            from core.metrics import refresh_active_conversations, refresh_active_sessions
            await refresh_active_conversations()
            await refresh_active_sessions()
            logger.info("background_cleanup_done")
        except Exception as e:
            logger.error("background_cleanup_error", error=str(e))


_cleanup_task: asyncio.Task[None] | None = None


def start_cleanup_task() -> None:
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_cleanup_loop())


def stop_cleanup_task() -> None:
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()

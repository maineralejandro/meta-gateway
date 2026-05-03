import asyncio

import structlog

logger = structlog.get_logger()

_inflight_tasks: set[asyncio.Task[None]] = set()
SHUTDOWN_TIMEOUT = 10


def track_task(task: asyncio.Task[None]) -> None:
    _inflight_tasks.add(task)
    task.add_done_callback(_inflight_tasks.discard)


async def wait_for_inflight() -> None:
    logger.info("shutdown_starting", inflight_tasks=len(_inflight_tasks))
    if _inflight_tasks:
        _done, pending = await asyncio.wait(_inflight_tasks.copy(), timeout=SHUTDOWN_TIMEOUT)
        if pending:
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            logger.warning("shutdown_cancelled_tasks", cancelled=len(pending))

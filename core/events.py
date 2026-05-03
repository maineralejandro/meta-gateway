import asyncio
from collections import defaultdict
from typing import Any

import structlog

logger = structlog.get_logger()

_subscribers: dict[str, list[Any]] = defaultdict(list)


def subscribe(event_type: str, handler: Any) -> None:
    _subscribers[event_type].append(handler)


async def emit(event_type: str, payload: dict[str, Any]) -> None:
    handlers = _subscribers.get(event_type, [])
    for handler in handlers:
        try:
            result = handler(payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error("event_handler_error", event_type=event_type, error=str(e))


def _ws_forwarder(event_type: str) -> Any:
    async def handler(payload: dict[str, Any]) -> None:
        from routers.ws import manager
        await manager.send_to_all({"type": event_type, **payload})
    return handler


def setup_default_subscribers() -> None:
    for event_type in ("new-message", "bot-replied", "escalated", "waiting-for-human", "state-changed", "human-sent", "error"):
        subscribe(event_type, _ws_forwarder(event_type))

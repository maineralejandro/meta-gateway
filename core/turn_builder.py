import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import structlog

from core.events import emit
from core.meta_client import meta_client

logger = structlog.get_logger()

DEBOUNCE_SECONDS = 2.0


@dataclass
class BufferedMessage:
    text: str
    correlation_id: str
    message_id: int
    session_id: str | None = None
    received_at: float = field(default_factory=time.monotonic)


class TurnBuilder:
    debounce_seconds: float = DEBOUNCE_SECONDS

    def __init__(self) -> None:
        self._buffers: dict[str, list[BufferedMessage]] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._process_turn_fn: Callable[..., Coroutine[Any, Any, None]] | None = None

    def set_process_turn_fn(self, fn: Callable[..., Coroutine[Any, Any, None]]) -> None:
        self._process_turn_fn = fn

    async def _dispatch_turn(self, phone: str, consolidated: str, correlation_id: str, message_ids: list[int], session_id: str | None = None) -> None:
        if self._process_turn_fn:
            await self._process_turn_fn(phone, consolidated, correlation_id, message_ids, session_id)
            return
        from core.hitl_router import hitl_router
        await hitl_router.process_turn(phone, consolidated, correlation_id, message_ids, session_id)

    def _consolidate(self, messages: list[BufferedMessage]) -> tuple[str, str, list[int], str | None]:
        parts: list[str] = []
        message_ids: list[int] = []
        correlation_id = messages[0].correlation_id
        session_id = messages[0].session_id
        for i, msg in enumerate(messages, 1):
            parts.append(f"[{i}] {msg.text}")
            message_ids.append(msg.message_id)
        consolidated = "\n\n".join(parts)
        return consolidated, correlation_id, message_ids, session_id

    async def debounce(
        self,
        phone: str,
        text: str,
        correlation_id: str,
        message_id: int,
        session_id: str | None = None,
    ) -> None:
        buffered = BufferedMessage(
            text=text,
            correlation_id=correlation_id,
            message_id=message_id,
            session_id=session_id,
        )
        if phone not in self._buffers:
            self._buffers[phone] = []
        self._buffers[phone].append(buffered)

        if phone in self._timers:
            self._timers[phone].cancel()

        self._timers[phone] = asyncio.create_task(
            self._fire_after_silence(phone, self.debounce_seconds)
        )

        logger.debug(
            "turn_builder_buffered",
            phone=phone,
            buffer_size=len(self._buffers[phone]),
            message_id=message_id,
        )

    async def _fire_after_silence(self, phone: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        messages = self._buffers.pop(phone, [])
        self._timers.pop(phone, None)

        if not messages:
            return

        consolidated, correlation_id, message_ids, session_id = self._consolidate(messages)

        logger.info(
            "turn_builder_firing",
            phone=phone,
            burst_count=len(messages),
            consolidated_length=len(consolidated),
            correlation_id=correlation_id,
        )

        try:
            await self._dispatch_turn(phone, consolidated, correlation_id, message_ids, session_id)
        except Exception as e:
            logger.error(
                "turn_builder_process_error",
                phone=phone,
                error=str(e),
                error_type=type(e).__name__,
            )
            try:
                await emit("error", {"phone": phone, "error": str(e)})
                await meta_client.send_text(
                    phone,
                    "Disculpa, ocurrio un error. Por favor intenta de nuevo.",
                )
            except Exception:
                logger.error("turn_builder_fallback_failed", phone=phone)

    async def flush(self, phone: str) -> None:
        if phone in self._timers:
            self._timers[phone].cancel()
            self._timers.pop(phone, None)

        messages = self._buffers.pop(phone, [])
        if not messages:
            return

        consolidated, correlation_id, message_ids, session_id = self._consolidate(messages)

        logger.info(
            "turn_builder_flush",
            phone=phone,
            burst_count=len(messages),
            consolidated_length=len(consolidated),
        )

        try:
            await self._dispatch_turn(phone, consolidated, correlation_id, message_ids, session_id)
        except Exception as e:
            logger.error(
                "turn_builder_flush_error",
                phone=phone,
                error=str(e),
                error_type=type(e).__name__,
            )

    def get_buffer_size(self, phone: str) -> int:
        return len(self._buffers.get(phone, []))


turn_builder = TurnBuilder()

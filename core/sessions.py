from datetime import UTC, datetime, timedelta
from typing import Any, cast

import structlog

from core.capabilities.base import registry as capability_registry

logger = structlog.get_logger()
SESSION_TIMEOUT_HOURS = 4


class SessionManager:
    def __init__(self, db: Any = None, memory_manager: Any = None) -> None:
        self._db = db
        self._memory = memory_manager

    async def _resolve_db(self) -> Any:
        if self._db is not None:
            return self._db
        from db.database import get_db
        return await get_db()

    async def _safe_summarize_session(self, phone: str, session_id: str) -> None:
        try:
            mem = self._memory
            if mem is None:
                from core.memory import memory_manager
                mem = memory_manager
            await mem.summarize_session(phone, session_id)
        except Exception as e:
            logger.error("safe_summarize_session_error", phone=phone, session_id=session_id, error=str(e))

    async def get_or_create_session(self, phone: str) -> str:
        _db = await self._resolve_db()
        conv = await _db.get_conversation(phone)

        if not conv:
            return cast(str, await _db.create_session(phone))

        if not conv.current_session_id:
            return cast(str, await _db.create_session(phone))

        if conv.last_message_at:
            try:
                last_msg_at = conv.last_message_at
                if isinstance(last_msg_at, datetime):
                    last_msg_time = last_msg_at if last_msg_at.tzinfo else last_msg_at.replace(tzinfo=UTC)
                elif " " in last_msg_at and "T" not in last_msg_at:
                    last_msg_time = datetime.strptime(last_msg_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                else:
                    last_msg_time = datetime.fromisoformat(last_msg_at.replace("Z", "+00:00"))

                elapsed = datetime.now(UTC) - last_msg_time

                if elapsed > timedelta(hours=SESSION_TIMEOUT_HOURS):
                    old_session_id = conv.current_session_id
                    await self._safe_summarize_session(phone, old_session_id)
                    await _db.close_session(
                        conv.current_session_id,
                        reason='timeout',
                    )
                    capabilities = await capability_registry.resolve(conv.agent_id)
                    for cap in capabilities:
                        await cap.clear(phone, cap.config)
                    logger.info(
                        "session_expired",
                        phone=phone,
                        old_session=conv.current_session_id,
                        hours_inactive=elapsed.total_seconds() / 3600,
                    )

                    if conv.state != "BOT_ACTIVE":
                        await _db.update_conversation_state(phone, "BOT_ACTIVE", requires_human_review=False)

                    return cast(str, await _db.create_session(phone))
            except Exception as e:
                logger.error("session_timeout_check_error", error=str(e), phone=phone)
                return cast(str, conv.current_session_id)

        return cast(str, conv.current_session_id)


session_manager = SessionManager()

from datetime import UTC, datetime, timedelta

import structlog

from core.order_state import order_state
from db.database import db

logger = structlog.get_logger()
SESSION_TIMEOUT_HOURS = 4

class SessionManager:
    async def get_or_create_session(self, phone: str) -> str:
        conv = await db.get_conversation(phone)

        if not conv:
            return await db.create_session(phone)

        if not conv.current_session_id:
            return await db.create_session(phone)

        if conv.last_message_at:
            try:
                last_msg_str = conv.last_message_at
                if " " in last_msg_str and "T" not in last_msg_str:
                    last_msg_time = datetime.strptime(last_msg_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                else:
                    last_msg_time = datetime.fromisoformat(last_msg_str.replace("Z", "+00:00"))

                elapsed = datetime.now(UTC) - last_msg_time

                if elapsed > timedelta(hours=SESSION_TIMEOUT_HOURS):
                    await db.close_session(
                        conv.current_session_id,
                        reason='timeout',
                    )
                    await order_state.clear(phone)
                    logger.info(
                        "session_expired",
                        phone=phone,
                        old_session=conv.current_session_id,
                        hours_inactive=elapsed.total_seconds() / 3600,
                    )

                    if conv.state != "BOT_ACTIVE":
                        await db.update_conversation_state(phone, "BOT_ACTIVE", requires_human_review=False)

                    return await db.create_session(phone)
            except Exception as e:
                logger.error("session_timeout_check_error", error=str(e), phone=phone)
                return conv.current_session_id

        return conv.current_session_id

session_manager = SessionManager()

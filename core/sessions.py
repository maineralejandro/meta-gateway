from datetime import UTC, datetime, timedelta

import structlog

from core.order_state import order_state
from db.database import db

logger = structlog.get_logger()
SESSION_TIMEOUT_HOURS = 4

class SessionManager:
    async def get_or_create_session(self, phone: str) -> str:
        """Retorna el session_id activo o crea uno nuevo si expiró."""
        conv = await db.get_conversation(phone)

        if not conv:
            # La conversación se crea usualmente en el webhook antes de llamar aquí.
            # Pero si por alguna razón no existe, la creamos con una sesión.
            return await db.create_session(phone)

        if not conv.current_session_id:
            # Conversación existente sin sesión (datos legacy)
            return await db.create_session(phone)

        # Verificar timeout
        if conv.last_message_at:
            try:
                # SQLite CURRENT_TIMESTAMP es UTC.
                # Formato: 2023-10-27 10:00:00 o ISO
                last_msg_str = conv.last_message_at
                if " " in last_msg_str and "T" not in last_msg_str:
                    # Formato SQLite standard: YYYY-MM-DD HH:MM:SS
                    last_msg_time = datetime.strptime(last_msg_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                else:
                    last_msg_time = datetime.fromisoformat(last_msg_str.replace("Z", "+00:00"))

                elapsed = datetime.now(UTC) - last_msg_time

                if elapsed > timedelta(hours=SESSION_TIMEOUT_HOURS):
                    # Cerrar sesión vieja
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

                    # Resetear estado a BOT_ACTIVE si estaba escalado por inactividad
                    if conv.state != "BOT_ACTIVE":
                        await db.execute(
                            "UPDATE conversations SET state='BOT_ACTIVE', requires_human_review=0 WHERE phone=?",
                            (phone,),
                        )
                        await db.commit()

                    return await db.create_session(phone)
            except Exception as e:
                logger.error("session_timeout_check_error", error=str(e), phone=phone)
                # En caso de error de parseo, asumimos que la sesión es válida para no interrumpir el flujo
                return conv.current_session_id

        return conv.current_session_id

session_manager = SessionManager()

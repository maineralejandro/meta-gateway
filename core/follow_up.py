import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from core.config import settings

logger = structlog.get_logger()

_locks: dict[str, asyncio.Lock] = {}


def _get_lock(phone: str) -> asyncio.Lock:
    return _locks.setdefault(phone, asyncio.Lock())


class FollowUpManager:
    def __init__(self) -> None:
        self._scheduler: Any = None

    def set_scheduler(self, scheduler: Any) -> None:
        self._scheduler = scheduler

    async def maybe_schedule(
        self,
        phone: str,
        triggered_by_message_id: str | None = None,
    ) -> int | None:
        if not self._scheduler:
            logger.warning("follow_up_scheduler_not_set")
            return None

        lock = _get_lock(phone)
        async with lock:
            db = await self._get_db()

            row = await db.fetchone(
                "SELECT state FROM conversations WHERE phone=$1",
                phone,
            )
            if not row:
                logger.debug("follow_up_skip_no_conversation", phone=phone)
                return None

            state = row["state"]
            if state in ("HUMAN_ONLY", "PENDING_APPROVAL"):
                logger.debug("follow_up_skip_escalated", phone=phone, state=state)
                return None

            pending = await db.fetchone(
                "SELECT id FROM scheduled_messages WHERE phone=$1 AND status='PENDING' LIMIT 1",
                phone,
            )
            if pending:
                logger.debug("follow_up_skip_pending_exists", phone=phone)
                return None

            last_inbound = await db.fetchone(
                "SELECT created_at FROM messages WHERE phone=$1 AND direction='inbound' ORDER BY created_at DESC LIMIT 1",
                phone,
            )
            if last_inbound:
                la = last_inbound["created_at"]
                if isinstance(la, str):
                    try:
                        la_dt = datetime.fromisoformat(la)
                        if la_dt.tzinfo is None:
                            la_dt = la_dt.replace(tzinfo=UTC)
                        elapsed = (datetime.now(tz=UTC) - la_dt).total_seconds()
                        if elapsed < settings.FOLLOW_UP_DELAY_MINUTES * 60 * 0.5:
                            logger.debug("follow_up_skip_recent_inbound", phone=phone, elapsed_sec=elapsed)
                            return None
                    except (ValueError, TypeError):
                        pass

            escalated = await db.fetchone(
                "SELECT id FROM agent_decisions WHERE phone=$1 AND escalate_reason IS NOT NULL LIMIT 1",
                phone,
            )
            if escalated:
                logger.debug("follow_up_skip_ever_escalated", phone=phone)
                return None

            scheduled_at = (datetime.now(tz=UTC) + timedelta(minutes=settings.FOLLOW_UP_DELAY_MINUTES)).isoformat()
            msg_id = await self._scheduler.schedule(
                phone=phone,
                template_name="follow_up",
                scheduled_at=scheduled_at,
                triggered_by_message_id=triggered_by_message_id,
            )
            logger.info("follow_up_scheduled", phone=phone, scheduled_at=scheduled_at, triggered_by=triggered_by_message_id)
            return int(msg_id)

    async def cancel_for_phone(self, phone: str) -> int:
        db = await self._get_db()
        result = await db.execute(
            "UPDATE scheduled_messages SET status='CANCELLED' WHERE phone=$1 AND status='PENDING' AND template_name='follow_up'",
            phone,
        )
        count = int(result.split()[-1]) if result else 0
        if count:
            logger.info("follow_up_cancelled", phone=phone, count=count)
        return count

    async def _get_db(self) -> Any:
        from db.database import get_db
        return await get_db()


follow_up_manager = FollowUpManager()

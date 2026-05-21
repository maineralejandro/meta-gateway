import asyncio
import contextlib
import json
from typing import Any

import structlog

from core.config import settings
from core.events import emit

logger = structlog.get_logger()


class MessageScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._re_engagement_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        self._re_engagement_task = asyncio.create_task(self._re_engagement_loop())
        logger.info("scheduler_started", poll_interval=settings.SCHEDULER_POLL_INTERVAL)

    async def stop(self) -> None:
        self._running = False
        for t in (self._task, self._re_engagement_task):
            if t and not t.done():
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
        logger.info("scheduler_stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._process_due_messages()
            except Exception as e:
                logger.error("scheduler_error", error=str(e))
            try:
                await asyncio.sleep(settings.SCHEDULER_POLL_INTERVAL)
            except asyncio.CancelledError:
                break

    async def _re_engagement_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(3600)
                count = await self.run_re_engagement()
                if count:
                    logger.info("re_engagement_run", scheduled=count)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("re_engagement_error", error=str(e))

    async def _process_due_messages(self) -> None:
        from core.meta_client import meta_client
        from db.database import get_db

        db = await get_db()
        due = await db.scheduled_messages.get_due(limit=50)
        if not due:
            return
        logger.info("scheduler_processing", count=len(due))
        for sm in due:
            if sm.id is None:
                continue
            try:
                components: list[dict[str, Any]] = []
                if sm.components_json:
                    with contextlib.suppress(json.JSONDecodeError, TypeError):
                        components = json.loads(sm.components_json) if isinstance(sm.components_json, str) else sm.components_json
                result = await meta_client.send_template(
                    sm.phone, sm.template_name, components=components,
                )
                if result.get("error"):
                    await db.scheduled_messages.mark_failed(sm.id)
                    logger.warning("scheduled_message_failed", id=sm.id, phone=sm.phone, detail=result.get("detail"))
                else:
                    await db.scheduled_messages.mark_sent(sm.id)
                    logger.info("scheduled_message_sent", id=sm.id, phone=sm.phone, template=sm.template_name)
                    await emit("scheduled-message-sent", {"id": sm.id, "phone": sm.phone, "template": sm.template_name})
            except Exception as e:
                logger.error("scheduled_message_exception", id=sm.id, error=str(e))
                with contextlib.suppress(Exception):
                    await db.scheduled_messages.mark_failed(sm.id)

    async def schedule(
        self,
        phone: str,
        template_name: str,
        scheduled_at: str,
        components_json: str = "[]",
        triggered_by_message_id: str | None = None,
    ) -> int:
        from db.database import get_db
        from db.models import ScheduledMessage

        db = await get_db()
        sm = ScheduledMessage(
            phone=phone,
            template_name=template_name,
            components_json=components_json,
            scheduled_at=scheduled_at,
            triggered_by_message_id=triggered_by_message_id,
            status="PENDING",
        )
        msg_id = await db.scheduled_messages.create(sm)
        logger.info("message_scheduled", id=msg_id, phone=phone, template=template_name, scheduled_at=scheduled_at)
        return msg_id

    async def run_re_engagement(self) -> int:
        from datetime import UTC, datetime, timedelta

        from db.database import get_db

        db = await get_db()
        rows = await db.fetchall(
            """SELECT c.phone FROM conversations c
            WHERE c.last_message_at < NOW() - make_interval(days => $1)
            AND c.state = 'BOT_ACTIVE'
            AND NOT EXISTS (
                SELECT 1 FROM scheduled_messages sm
                WHERE sm.phone = c.phone AND sm.status = 'PENDING'
            )
            LIMIT 100""",
            settings.RE_ENGAGEMENT_DAYS,
        )
        if not rows:
            return 0
        scheduled = 0
        send_at = (datetime.now(tz=UTC) + timedelta(minutes=5)).isoformat()
        for row in rows:
            phone = row["phone"]
            try:
                await self.schedule(phone, "follow_up", send_at)
                scheduled += 1
            except Exception as e:
                logger.warning("re_engagement_schedule_failed", phone=phone, error=str(e))
        logger.info("re_engagement_scheduled", count=scheduled)
        return scheduled


message_scheduler = MessageScheduler()

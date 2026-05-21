import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.scheduled_messages = AsyncMock()
    return db


@pytest.fixture
def mock_meta_client():
    mc = AsyncMock()
    mc.send_template = AsyncMock(return_value={"messages": [{"id": "wamid_123"}]})
    return mc


class TestScheduledMessageModel:
    def test_scheduled_message_defaults(self):
        from db.models import ScheduledMessage
        sm = ScheduledMessage()
        assert sm.id is None
        assert sm.phone == ""
        assert sm.template_name == ""
        assert sm.components_json == "[]"
        assert sm.status == "PENDING"
        assert sm.sent_at is None

    def test_row_to_scheduled_message(self):
        from db.models import row_to_scheduled_message
        row = {"id": 1, "phone": "+1234", "template_name": "follow_up", "components_json": "[]",
               "scheduled_at": "2026-01-01T00:00:00", "triggered_by_message_id": None,
               "status": "PENDING", "sent_at": None, "created_at": "2026-01-01T00:00:00"}
        sm = row_to_scheduled_message(row)
        assert sm is not None
        assert sm.id == 1
        assert sm.phone == "+1234"
        assert sm.template_name == "follow_up"

    def test_row_to_scheduled_message_none(self):
        from db.models import row_to_scheduled_message
        assert row_to_scheduled_message(None) is None


class TestScheduledMessageRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        from db.models import ScheduledMessage
        from db.repositories.scheduled_message import ScheduledMessageRepository
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 42})
        mock_pool.acquire = MagicMock(return_value=mock_conn.__aenter__.return_value)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire = MagicMock(return_value=mock_conn)

        repo = ScheduledMessageRepository(get_pool_fn=lambda: asyncio.coroutine(lambda: mock_pool)())
        repo._get_pool = AsyncMock(return_value=mock_pool)
        repo._insert_returning_id = AsyncMock(return_value=42)

        sm = ScheduledMessage(phone="+1234", template_name="follow_up",
                              components_json="[]", scheduled_at="2026-01-01T00:00:00+00:00")
        result = await repo.create(sm)
        assert result == 42
        repo._insert_returning_id.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_sent(self):
        from db.repositories.scheduled_message import ScheduledMessageRepository
        repo = ScheduledMessageRepository()
        repo._execute = AsyncMock()
        await repo.mark_sent(1)
        repo._execute.assert_called_once_with(
            "UPDATE scheduled_messages SET status='SENT', sent_at=NOW() WHERE id=$1", 1
        )

    @pytest.mark.asyncio
    async def test_mark_failed(self):
        from db.repositories.scheduled_message import ScheduledMessageRepository
        repo = ScheduledMessageRepository()
        repo._execute = AsyncMock()
        await repo.mark_failed(2)
        repo._execute.assert_called_once_with(
            "UPDATE scheduled_messages SET status='FAILED' WHERE id=$1", 2
        )

    @pytest.mark.asyncio
    async def test_cancel(self):
        from db.repositories.scheduled_message import ScheduledMessageRepository
        repo = ScheduledMessageRepository()
        repo._execute = AsyncMock()
        await repo.cancel(3)
        repo._execute.assert_called_once_with(
            "UPDATE scheduled_messages SET status='CANCELLED' WHERE id=$1", 3
        )

    @pytest.mark.asyncio
    async def test_has_pending_for_phone(self):
        from db.repositories.scheduled_message import ScheduledMessageRepository
        repo = ScheduledMessageRepository()
        repo._fetchone = AsyncMock(return_value={"?column?": 1})
        assert await repo.has_pending_for_phone("+1234") is True
        repo._fetchone = AsyncMock(return_value=None)
        assert await repo.has_pending_for_phone("+1234") is False

    @pytest.mark.asyncio
    async def test_has_pending_for_phone_with_template(self):
        from db.repositories.scheduled_message import ScheduledMessageRepository
        repo = ScheduledMessageRepository()
        repo._fetchone = AsyncMock(return_value={"?column?": 1})
        assert await repo.has_pending_for_phone("+1234", "follow_up") is True


class TestMessageScheduler:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        from core.scheduler import MessageScheduler
        scheduler = MessageScheduler()
        scheduler._poll_loop = AsyncMock()
        scheduler._re_engagement_loop = AsyncMock()
        await scheduler.start()
        assert scheduler._running is True
        assert scheduler._task is not None
        await scheduler.stop()
        assert scheduler._running is False

    @pytest.mark.asyncio
    async def test_process_due_messages_success(self):
        from core.scheduler import MessageScheduler
        from db.models import ScheduledMessage

        scheduler = MessageScheduler()
        sm = ScheduledMessage(id=1, phone="+1234", template_name="follow_up", components_json="[]")

        mock_db = AsyncMock()
        mock_db.scheduled_messages.get_due = AsyncMock(return_value=[sm])
        mock_db.scheduled_messages.mark_sent = AsyncMock()

        mock_meta = AsyncMock()
        mock_meta.send_template = AsyncMock(return_value={"messages": [{"id": "wamid_abc"}]})

        with patch("db.database.get_db", return_value=mock_db), \
             patch("core.meta_client.meta_client", mock_meta), \
             patch("core.scheduler.emit", new_callable=AsyncMock):
            await scheduler._process_due_messages()

        mock_db.scheduled_messages.mark_sent.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_process_due_messages_failure(self):
        from core.scheduler import MessageScheduler
        from db.models import ScheduledMessage

        scheduler = MessageScheduler()
        sm = ScheduledMessage(id=2, phone="+5678", template_name="follow_up", components_json="[]")

        mock_db = AsyncMock()
        mock_db.scheduled_messages.get_due = AsyncMock(return_value=[sm])
        mock_db.scheduled_messages.mark_failed = AsyncMock()

        mock_meta = AsyncMock()
        mock_meta.send_template = AsyncMock(return_value={"error": True, "detail": "rate limited"})

        with patch("db.database.get_db", return_value=mock_db), \
             patch("core.meta_client.meta_client", mock_meta):
            await scheduler._process_due_messages()

        mock_db.scheduled_messages.mark_failed.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_process_due_messages_empty(self):
        from core.scheduler import MessageScheduler

        scheduler = MessageScheduler()
        mock_db = AsyncMock()
        mock_db.scheduled_messages.get_due = AsyncMock(return_value=[])

        with patch("db.database.get_db", return_value=mock_db):
            await scheduler._process_due_messages()

    @pytest.mark.asyncio
    async def test_schedule_creates_message(self):
        from core.scheduler import MessageScheduler

        scheduler = MessageScheduler()
        mock_db = AsyncMock()
        mock_db.scheduled_messages.create = AsyncMock(return_value=10)

        with patch("db.database.get_db", return_value=mock_db):
            msg_id = await scheduler.schedule(
                phone="+1234",
                template_name="follow_up",
                scheduled_at="2026-01-01T01:00:00+00:00",
            )
        assert msg_id == 10
        mock_db.scheduled_messages.create.assert_called_once()


class TestFollowUpOnDelivered:
    @pytest.mark.asyncio
    async def test_delivered_schedules_follow_up(self):
        mock_scheduler = AsyncMock()
        mock_scheduler.schedule = AsyncMock(return_value=99)

        with patch("core.scheduler.message_scheduler", mock_scheduler):
            from core.config import settings
            scheduled_at = (datetime.now(tz=UTC) + timedelta(minutes=settings.FOLLOW_UP_DELAY_MINUTES)).isoformat()
            await mock_scheduler.schedule(
                phone="+1234",
                template_name="follow_up",
                scheduled_at=scheduled_at,
                triggered_by_message_id="wamid_delivered",
            )
            mock_scheduler.schedule.assert_called_once()
            call_kwargs = mock_scheduler.schedule.call_args
            assert call_kwargs.kwargs["phone"] == "+1234"
            assert call_kwargs.kwargs["template_name"] == "follow_up"
            assert call_kwargs.kwargs["triggered_by_message_id"] == "wamid_delivered"


class TestAppointmentReminder:
    @pytest.mark.asyncio
    async def test_reminder_scheduled_on_appointment_add(self):
        from core.capabilities.appointment import AppointmentCapability
        cap = AppointmentCapability()
        cap._ensure_loaded = AsyncMock()
        cap._appointments = {"+1234": []}
        cap._persist_appointment = AsyncMock()

        mock_scheduler = AsyncMock()
        mock_scheduler.schedule = AsyncMock(return_value=55)

        future_date = (datetime.now(tz=UTC) + timedelta(days=3)).strftime("%Y-%m-%d")
        with patch("core.scheduler.message_scheduler", mock_scheduler):
            await cap.add_appointment("+1234", future_date, "10:00", "checkup")

        cap._persist_appointment.assert_called_once()
        mock_scheduler.schedule.assert_called_once()
        call_kwargs = mock_scheduler.schedule.call_args
        assert call_kwargs.kwargs["template_name"] == "appointment_reminder"
        assert call_kwargs.kwargs["phone"] == "+1234"

    @pytest.mark.asyncio
    async def test_reminder_not_scheduled_for_past_appointment(self):
        from core.capabilities.appointment import AppointmentCapability
        cap = AppointmentCapability()
        cap._ensure_loaded = AsyncMock()
        cap._appointments = {"+1234": []}
        cap._persist_appointment = AsyncMock()

        mock_scheduler = AsyncMock()
        mock_scheduler.schedule = AsyncMock(return_value=55)

        with patch("core.scheduler.message_scheduler", mock_scheduler):
            await cap.add_appointment("+1234", "2020-01-01", "10:00", "checkup")

        cap._persist_appointment.assert_called_once()
        mock_scheduler.schedule.assert_not_called()


class TestScheduledMessagesRouter:
    @pytest.mark.asyncio
    async def test_list_scheduled_messages(self):
        from db.models import ScheduledMessage
        mock_db = AsyncMock()
        sm = ScheduledMessage(id=1, phone="+1234", template_name="follow_up",
                              components_json="[]", status="PENDING")
        mock_db.scheduled_messages.get_all = AsyncMock(return_value=[sm])

        with patch("routers.scheduled_messages.get_db", return_value=mock_db):
            from routers.scheduled_messages import list_scheduled_messages
            result = await list_scheduled_messages()
        assert len(result) == 1
        assert result[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_cancel_scheduled_message(self):
        from db.models import ScheduledMessage
        mock_db = AsyncMock()
        sm = ScheduledMessage(id=5, phone="+1234", template_name="follow_up", status="PENDING")
        mock_db.scheduled_messages.get = AsyncMock(return_value=sm)
        mock_db.scheduled_messages.cancel = AsyncMock()

        with patch("routers.scheduled_messages.get_db", return_value=mock_db):
            from routers.scheduled_messages import cancel_scheduled_message
            await cancel_scheduled_message(5)
        mock_db.scheduled_messages.cancel.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_cancel_non_pending_raises(self):
        from db.models import ScheduledMessage
        mock_db = AsyncMock()
        sm = ScheduledMessage(id=6, phone="+1234", template_name="follow_up", status="SENT")
        mock_db.scheduled_messages.get = AsyncMock(return_value=sm)

        with patch("routers.scheduled_messages.get_db", return_value=mock_db):
            from fastapi import HTTPException

            from routers.scheduled_messages import cancel_scheduled_message
            with pytest.raises(HTTPException) as exc_info:
                await cancel_scheduled_message(6)
            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_not_found_raises(self):
        mock_db = AsyncMock()
        mock_db.scheduled_messages.get = AsyncMock(return_value=None)

        with patch("routers.scheduled_messages.get_db", return_value=mock_db):
            from fastapi import HTTPException

            from routers.scheduled_messages import cancel_scheduled_message
            with pytest.raises(HTTPException) as exc_info:
                await cancel_scheduled_message(999)
            assert exc_info.value.status_code == 404


class TestReEngagement:
    @pytest.mark.asyncio
    async def test_re_engagement_schedules_messages(self):
        from core.scheduler import MessageScheduler
        scheduler = MessageScheduler()
        scheduler.schedule = AsyncMock(side_effect=[1, 2])

        mock_db = AsyncMock()
        mock_db.fetchall = AsyncMock(return_value=[
            {"phone": "+1111"}, {"phone": "+2222"},
        ])

        with patch("db.database.get_db", return_value=mock_db):
            count = await scheduler.run_re_engagement()

        assert count == 2
        assert scheduler.schedule.call_count == 2

    @pytest.mark.asyncio
    async def test_re_engagement_no_inactive(self):
        from core.scheduler import MessageScheduler
        scheduler = MessageScheduler()
        scheduler.schedule = AsyncMock()

        mock_db = AsyncMock()
        mock_db.fetchall = AsyncMock(return_value=[])

        with patch("db.database.get_db", return_value=mock_db):
            count = await scheduler.run_re_engagement()

        assert count == 0
        scheduler.schedule.assert_not_called()


class TestConfigSettings:
    def test_follow_up_delay_minutes(self):
        from core.config import settings
        assert settings.FOLLOW_UP_DELAY_MINUTES == 30

    def test_re_engagement_days(self):
        from core.config import settings
        assert settings.RE_ENGAGEMENT_DAYS == 7

    def test_scheduler_poll_interval(self):
        from core.config import settings
        assert settings.SCHEDULER_POLL_INTERVAL == 60

from __future__ import annotations

from typing import Any

from db.models import ScheduledMessage, row_to_scheduled_message
from db.repositories.base import BaseRepository


class ScheduledMessageRepository(BaseRepository):

    async def create(self, sm: ScheduledMessage) -> int:
        return await self._insert_returning_id(
            """INSERT INTO scheduled_messages
            (phone, template_name, components_json, scheduled_at, triggered_by_message_id, status)
            VALUES ($1, $2, $3::jsonb, $4, $5, $6)
            RETURNING id""",
            sm.phone, sm.template_name, sm.components_json,
            sm.scheduled_at, sm.triggered_by_message_id, sm.status,
        )

    async def get(self, msg_id: int) -> ScheduledMessage | None:
        row = await self._fetchone(
            "SELECT * FROM scheduled_messages WHERE id=$1", msg_id
        )
        return row_to_scheduled_message(row)

    async def get_all(
        self,
        phone: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ScheduledMessage]:
        clauses: list[str] = []
        args: list[Any] = []
        idx = 1
        if phone is not None:
            clauses.append(f"phone=${idx}")
            args.append(phone)
            idx += 1
        if status is not None:
            clauses.append(f"status=${idx}")
            args.append(status)
            idx += 1
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(limit)
        args.append(offset)
        rows = await self._fetchall(
            f"SELECT * FROM scheduled_messages{where} ORDER BY scheduled_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *args,
        )
        return [r for r in (row_to_scheduled_message(row) for row in rows) if r is not None]

    async def get_due(self, limit: int = 50) -> list[ScheduledMessage]:
        rows = await self._fetchall(
            """SELECT id, phone, template_name, components_json
            FROM scheduled_messages
            WHERE status = 'PENDING' AND scheduled_at <= NOW()
            ORDER BY scheduled_at LIMIT $1""",
            limit,
        )
        return [r for r in (row_to_scheduled_message(row) for row in rows) if r is not None]

    async def mark_sent(self, msg_id: int) -> None:
        await self._execute(
            "UPDATE scheduled_messages SET status='SENT', sent_at=NOW() WHERE id=$1",
            msg_id,
        )

    async def mark_failed(self, msg_id: int) -> None:
        await self._execute(
            "UPDATE scheduled_messages SET status='FAILED' WHERE id=$1",
            msg_id,
        )

    async def cancel(self, msg_id: int) -> None:
        await self._execute(
            "UPDATE scheduled_messages SET status='CANCELLED' WHERE id=$1",
            msg_id,
        )

    async def delete(self, msg_id: int) -> None:
        await self._execute(
            "DELETE FROM scheduled_messages WHERE id=$1",
            msg_id,
        )

    async def has_pending_for_phone(self, phone: str, template_name: str | None = None) -> bool:
        if template_name:
            row = await self._fetchone(
                "SELECT 1 FROM scheduled_messages WHERE phone=$1 AND status='PENDING' AND template_name=$2 LIMIT 1",
                phone, template_name,
            )
        else:
            row = await self._fetchone(
                "SELECT 1 FROM scheduled_messages WHERE phone=$1 AND status='PENDING' LIMIT 1",
                phone,
            )
        return row is not None

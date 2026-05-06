from __future__ import annotations

from typing import Any

from db.models import Session, Turn, row_to_session, row_to_turn
from db.repositories.base import BaseRepository


class SessionRepository(BaseRepository):
    async def create(self, phone: str) -> str:
        import uuid
        session_id = str(uuid.uuid4())
        conn = await self._get_conn()
        await conn.execute(
            "INSERT INTO sessions (id, phone) VALUES (?, ?)",
            (session_id, phone),
        )
        await conn.execute(
            "UPDATE conversations SET current_session_id=? WHERE phone=?",
            (session_id, phone),
        )
        await conn.commit()
        from core.metrics import refresh_active_sessions
        await refresh_active_sessions()
        return session_id

    async def get_active(self, phone: str) -> Session | None:
        row = await self._fetchone(
            "SELECT * FROM sessions WHERE phone=? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            (phone,),
        )
        return row_to_session(row)

    async def close(self, session_id: str, reason: str, summary: str | None = None) -> None:
        conn = await self._get_conn()
        await conn.execute(
            "UPDATE sessions SET ended_at=CURRENT_TIMESTAMP, end_reason=?, summary=? WHERE id=?",
            (reason, summary, session_id),
        )
        await conn.commit()
        from core.metrics import refresh_active_sessions
        await refresh_active_sessions()

    async def increment_message_count(self, session_id: str) -> None:
        await self._execute_and_commit(
            "UPDATE sessions SET message_count = message_count + 1 WHERE id=?", (session_id,),
        )

    async def get_summaries(self, phone: str, limit: int = 5) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            """SELECT id, started_at, summary FROM sessions
            WHERE phone=? AND summary IS NOT NULL AND summary != ''
            ORDER BY started_at DESC LIMIT ?""",
            (phone, limit),
        )
        return [{"session_id": row["id"], "started_at": row["started_at"], "summary": row["summary"]} for row in rows]

    async def update_summary(self, session_id: str, summary: str) -> None:
        await self._execute_and_commit(
            "UPDATE sessions SET summary=? WHERE id=?",
            (summary, session_id),
        )


class TurnRepository(BaseRepository):
    async def insert(self, turn: Turn) -> int:
        return await self._insert_returning_id(
            """INSERT INTO turns (phone, user_text, assistant_text, user_correlation_id, assistant_correlation_id, message_ids, session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (turn.phone, turn.user_text, turn.assistant_text, turn.user_correlation_id, turn.assistant_correlation_id, turn.message_ids, turn.session_id),
        )

    async def get(self, phone: str, limit: int = 16, desc: bool = False) -> list[Turn]:
        order = "DESC" if desc else "ASC"
        rows = await self._fetchall(
            f"""SELECT id, phone, user_text, assistant_text, user_correlation_id, assistant_correlation_id, message_ids, session_id, created_at
            FROM turns WHERE phone=? ORDER BY id {order} LIMIT ?""",
            (phone, limit),
        )
        return [t for r in rows if (t := row_to_turn(r)) is not None]

    async def count(self, phone: str) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) as cnt FROM turns WHERE phone=?",
            (phone,),
        )
        return row["cnt"] if row else 0

    async def get_last(self, phone: str) -> Turn | None:
        row = await self._fetchone(
            """SELECT id, phone, user_text, assistant_text, user_correlation_id, assistant_correlation_id, message_ids, session_id, created_at
            FROM turns WHERE phone=? ORDER BY id DESC LIMIT 1""",
            (phone,),
        )
        return row_to_turn(row)

    async def get_by_session(self, session_id: str) -> list[Turn]:
        rows = await self._fetchall(
            """SELECT id, phone, user_text, assistant_text, user_correlation_id, assistant_correlation_id, message_ids, session_id, created_at
            FROM turns WHERE session_id=? ORDER BY id ASC""",
            (session_id,),
        )
        return [t for r in rows if (t := row_to_turn(r)) is not None]

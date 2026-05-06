from __future__ import annotations

from db.models import (
    Conversation,
    Message,
    row_to_conversation,
    row_to_message,
)
from db.repositories.base import BaseRepository


class ConversationRepository(BaseRepository):
    async def create(self, phone: str, agent_id: int = 1) -> None:
        await self._execute_and_commit(
            "INSERT INTO conversations (phone, state, agent_id, last_message_at) VALUES (?, 'BOT_ACTIVE', ?, CURRENT_TIMESTAMP)",
            (phone, agent_id),
        )

    async def get(self, phone: str) -> Conversation | None:
        row = await self._fetchone(
            """SELECT phone, contact_name, state, last_message_at,
               requires_human_review, unread_count, sentiment_score, confidence, agent_id, current_session_id, created_at
               FROM conversations WHERE phone=?""",
            (phone,),
        )
        return row_to_conversation(row)

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[Conversation]:
        rows = await self._fetchall(
            """SELECT phone, contact_name, state, last_message_at,
            requires_human_review, unread_count, sentiment_score, confidence, agent_id, current_session_id, created_at
            FROM conversations ORDER BY last_message_at DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        return [c for r in rows if (c := row_to_conversation(r)) is not None]

    async def update_state(self, phone: str, state: str, requires_human_review: bool = False) -> None:
        await self._execute_and_commit(
            "UPDATE conversations SET state=?, requires_human_review=? WHERE phone=?",
            (state, int(requires_human_review), phone),
        )

    async def update_sentiment(self, phone: str, sentiment_score: float, confidence: float) -> None:
        await self._execute_and_commit(
            "UPDATE conversations SET sentiment_score=?, confidence=? WHERE phone=?",
            (sentiment_score, confidence, phone),
        )

    async def escalate(self, phone: str, sentiment_score: float, confidence: float, reason: str) -> None:
        await self._execute_transaction([
            (
                "UPDATE conversations SET sentiment_score=?, confidence=?, state='PENDING_APPROVAL', requires_human_review=1 WHERE phone=?",
                (sentiment_score, confidence, phone),
            ),
            (
                "INSERT INTO escalation_events (phone, from_state, to_state, reason, sentiment_score, confidence) VALUES (?, 'BOT_ACTIVE', 'PENDING_APPROVAL', ?, ?, ?)",
                (phone, reason, sentiment_score, confidence),
            ),
        ])

    async def reset_session(self, phone: str) -> None:
        await self._execute_and_commit(
            "UPDATE conversations SET current_session_id=NULL, state='BOT_ACTIVE', requires_human_review=0 WHERE phone=?",
            (phone,),
        )

    async def set_agent(self, phone: str, agent_id: int) -> None:
        await self._execute_and_commit(
            "UPDATE conversations SET agent_id=? WHERE phone=?", (agent_id, phone),
        )


class MessageRepository(BaseRepository):
    async def get(self, phone: str, limit: int = 100, desc: bool = False) -> list[Message]:
        order = "DESC" if desc else "ASC"
        rows = await self._fetchall(
            f"""SELECT id, phone, direction, source, text, media_type, media_url, meta_message_id, session_id, correlation_id, created_at
            FROM messages WHERE phone=? ORDER BY created_at {order} LIMIT ?""",
            (phone, limit),
        )
        return [m for r in rows if (m := row_to_message(r)) is not None]

    async def insert(
        self,
        phone: str,
        direction: str,
        source: str,
        text: str,
        session_id: str | None = None,
        media_type: str | None = None,
        media_url: str | None = None,
        meta_message_id: str | None = None,
        correlation_id: str | None = None,
    ) -> int:
        return await self._insert_returning_id(
            """INSERT INTO messages (phone, direction, source, text, media_type, media_url, meta_message_id, session_id, correlation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (phone, direction, source, text, media_type, media_url, meta_message_id, session_id, correlation_id),
        )

    async def count(self, phone: str) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) as cnt FROM messages WHERE phone=?",
            (phone,),
        )
        return row["cnt"] if row else 0

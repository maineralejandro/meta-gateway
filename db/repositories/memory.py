from __future__ import annotations

from db.models import ConversationMemory, row_to_memory
from db.repositories.base import BaseRepository


class MemoryRepository(BaseRepository):
    async def get(self, phone: str) -> ConversationMemory | None:
        row = await self._fetchone(
            "SELECT * FROM conversation_memory WHERE phone=?",
            (phone,),
        )
        return row_to_memory(row)

    async def upsert(self, phone: str, summary: str, key_facts: str, total_count: int) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO conversation_memory (phone, summary, key_facts, total_messages_summarized, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(phone) DO UPDATE SET
               summary=excluded.summary,
               key_facts=excluded.key_facts,
               total_messages_summarized=excluded.total_messages_summarized,
               updated_at=CURRENT_TIMESTAMP""",
            (phone, summary, key_facts, total_count),
        )
        await conn.commit()

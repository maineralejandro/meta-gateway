import aiosqlite
import os
import sqlite3
from pathlib import Path
from core.config import settings
from db.models import Conversation, Message, row_to_conversation, row_to_message

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    def __init__(self):
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            os.makedirs(settings.DB_DIR, exist_ok=True)
            self._conn = await aiosqlite.connect(settings.DB_PATH)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    async def execute(self, query: str, params: tuple = ()):
        conn = await self._get_conn()
        await conn.execute(query, params)

    async def executemany(self, query: str, params: list[tuple]):
        conn = await self._get_conn()
        await conn.executemany(query, params)

    async def fetchone(self, query: str, params: tuple = ()):
        conn = await self._get_conn()
        cursor = await conn.execute(query, params)
        return await cursor.fetchone()

    async def fetchall(self, query: str, params: tuple = ()):
        conn = await self._get_conn()
        cursor = await conn.execute(query, params)
        return await cursor.fetchall()

    async def commit(self):
        if self._conn:
            await self._conn.commit()

    async def execute_transaction(self, operations: list[tuple[str, tuple]]):
        conn = await self._get_conn()
        try:
            for query, params in operations:
                await conn.execute(query, params)
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def get_conversation(self, phone: str) -> Conversation | None:
        row = await self.fetchone(
            """SELECT phone, contact_name, state, last_message_at,
               requires_human_review, unread_count, sentiment_score, confidence, created_at
               FROM conversations WHERE phone=?""",
            (phone,),
        )
        return row_to_conversation(row)

    async def get_all_conversations(self) -> list[Conversation]:
        rows = await self.fetchall(
            """SELECT phone, contact_name, state, last_message_at,
               requires_human_review, unread_count, sentiment_score, confidence, created_at
               FROM conversations ORDER BY last_message_at DESC"""
        )
        return [row_to_conversation(r) for r in rows]

    async def get_messages(self, phone: str, limit: int = 100) -> list[Message]:
        rows = await self.fetchall(
            """SELECT id, phone, direction, source, text, media_type, media_url, meta_message_id, created_at
               FROM messages WHERE phone=? ORDER BY created_at ASC LIMIT ?""",
            (phone, limit),
        )
        return [row_to_message(r) for r in rows]

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None


db = Database()


async def init_db():
    schema = SCHEMA_PATH.read_text()
    os.makedirs(settings.DB_DIR, exist_ok=True)
    sync_conn = sqlite3.connect(settings.DB_PATH)
    sync_conn.executescript(schema)
    sync_conn.close()
    await db._get_conn()


async def get_db() -> Database:
    return db


async def close_db():
    await db.close()

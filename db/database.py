import aiosqlite
import os
import sqlite3
from pathlib import Path
from core.config import settings
from db.models import (
    Agent,
    AgentDecision,
    Conversation,
    ConversationMemory,
    Message,
    Session,
    row_to_agent,
    row_to_agent_decision,
    row_to_conversation,
    row_to_memory,
    row_to_message,
    row_to_session,
)

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
               requires_human_review, unread_count, sentiment_score, confidence, agent_id, current_session_id, created_at
               FROM conversations WHERE phone=?""",
            (phone,),
        )
        return row_to_conversation(row)

    async def get_all_conversations(self) -> list[Conversation]:
        rows = await self.fetchall(
            """SELECT phone, contact_name, state, last_message_at,
               requires_human_review, unread_count, sentiment_score, confidence, agent_id, current_session_id, created_at
               FROM conversations ORDER BY last_message_at DESC"""
        )
        return [row_to_conversation(r) for r in rows]

    async def get_messages(self, phone: str, limit: int = 100) -> list[Message]:
        rows = await self.fetchall(
            """SELECT id, phone, direction, source, text, media_type, media_url, meta_message_id, session_id, created_at
               FROM messages WHERE phone=? ORDER BY created_at ASC LIMIT ?""",
            (phone, limit),
        )
        return [row_to_message(r) for r in rows]

    # --- Agent Methods ---

    async def get_agent(self, agent_id: int | None = None, is_active: bool = False) -> Agent | None:
        if agent_id:
            row = await self.fetchone("SELECT * FROM agents WHERE id=?", (agent_id,))
        elif is_active:
            row = await self.fetchone(
                "SELECT * FROM agents WHERE is_active=1 ORDER BY updated_at DESC LIMIT 1"
            )
        else:
            row = await self.fetchone("SELECT * FROM agents ORDER BY updated_at DESC LIMIT 1")
        return row_to_agent(row)

    async def get_all_agents(self) -> list[Agent]:
        rows = await self.fetchall("SELECT * FROM agents ORDER BY name ASC")
        return [row_to_agent(r) for r in rows if r]

    async def upsert_agent(self, agent: Agent) -> int:
        if agent.id:
            await self.execute(
                """UPDATE agents SET name=?, description=?, system_prompt=?,
                   escalation_marker=?, fallback_responses=?, is_active=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (
                    agent.name,
                    agent.description,
                    agent.system_prompt,
                    agent.escalation_marker,
                    agent.fallback_responses,
                    agent.is_active,
                    agent.id,
                ),
            )
            await self.commit()
            return agent.id
        else:
            conn = await self._get_conn()
            cursor = await conn.execute(
                """INSERT INTO agents (name, description, system_prompt, escalation_marker, fallback_responses, is_active)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    agent.name,
                    agent.description,
                    agent.system_prompt,
                    agent.escalation_marker,
                    agent.fallback_responses,
                    agent.is_active,
                ),
            )
            await self.commit()
            return cursor.lastrowid

    async def activate_agent(self, agent_id: int):
        await self.execute_transaction(
            [
                ("UPDATE agents SET is_active=0", ()),
                ("UPDATE agents SET is_active=1 WHERE id=?", (agent_id,)),
            ]
        )

    async def insert_agent_decision(self, decision: AgentDecision) -> int:
        conn = await self._get_conn()
        cursor = await conn.execute(
            """INSERT INTO agent_decisions
            (message_id, phone, sentiment, sentiment_score, confidence,
             llm_escalate, escalate_reason, history_count, agent_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision.message_id,
                decision.phone,
                decision.sentiment,
                decision.sentiment_score,
                decision.confidence,
                decision.llm_escalate,
                decision.escalate_reason,
                decision.history_count,
                decision.agent_name,
            ),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_decisions(self, phone: str, limit: int = 50) -> list[AgentDecision]:
        rows = await self.fetchall(
            """SELECT ad.* FROM agent_decisions ad
            JOIN messages m ON ad.message_id = m.id
            WHERE m.phone = ?
            ORDER BY ad.created_at DESC LIMIT ?""",
            (phone, limit),
        )
        return [row_to_agent_decision(r) for r in rows if r]

    async def get_decision_for_message(self, message_id: int) -> AgentDecision | None:
        row = await self.fetchone(
            "SELECT * FROM agent_decisions WHERE message_id=?",
            (message_id,),
        )
        return row_to_agent_decision(row)

    # --- Memory Methods ---

    async def get_memory(self, phone: str) -> ConversationMemory | None:
        row = await self.fetchone(
            "SELECT * FROM conversation_memory WHERE phone=?",
            (phone,),
        )
        return row_to_memory(row)

    async def upsert_memory(self, phone: str, summary: str, key_facts: str, total_count: int):
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

    async def count_messages(self, phone: str) -> int:
        row = await self.fetchone(
            "SELECT COUNT(*) as cnt FROM messages WHERE phone=?",
            (phone,),
        )
        return row["cnt"] if row else 0

    # --- Session Methods ---

    async def create_session(self, phone: str) -> str:
        """Crea una nueva sesión y retorna su ID."""
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
        return session_id

    async def get_active_session(self, phone: str) -> Session | None:
        row = await self.fetchone(
            "SELECT * FROM sessions WHERE phone=? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            (phone,),
        )
        return row_to_session(row)

    async def close_session(self, session_id: str, reason: str, summary: str = None):
        conn = await self._get_conn()
        await conn.execute(
            "UPDATE sessions SET ended_at=CURRENT_TIMESTAMP, end_reason=?, summary=? WHERE id=?",
            (reason, summary, session_id),
        )
        await conn.commit()

    async def increment_session_message_count(self, session_id: str):
        conn = await self._get_conn()
        await conn.execute(
            "UPDATE sessions SET message_count = message_count + 1 WHERE id=?",
            (session_id,),
        )
        await conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None


db = Database()


async def init_db():
    from db.migrator import run_migrations
    os.makedirs(settings.DB_DIR, exist_ok=True)
    run_migrations(settings.DB_PATH)
    await db._get_conn()


async def get_db() -> Database:
    return db


async def close_db():
    await db.close()

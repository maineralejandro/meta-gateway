import asyncio
import os
from pathlib import Path
from typing import Any

import aiosqlite

from core.config import settings
from db.models import (
    Agent,
    AgentCapability,
    AgentDecision,
    AgentTemplate,
    Conversation,
    ConversationMemory,
    InferenceTrace,
    Message,
    Session,
    Turn,
    row_to_agent,
    row_to_agent_capability,
    row_to_agent_decision,
    row_to_agent_template,
    row_to_conversation,
    row_to_inference_trace,
    row_to_memory,
    row_to_message,
    row_to_session,
    row_to_turn,
)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None
        self._init_lock = asyncio.Lock()

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is not None:
            return self._conn
        async with self._init_lock:
            if self._conn is not None:
                return self._conn
            os.makedirs(settings.DB_DIR, exist_ok=True)
            self._conn = await aiosqlite.connect(settings.DB_PATH)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            await self._conn.execute("PRAGMA busy_timeout=5000")
            return self._conn

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        conn = await self._get_conn()
        await conn.execute(query, params)

    async def executemany(self, query: str, params: list[tuple[Any, ...]]) -> None:
        conn = await self._get_conn()
        await conn.executemany(query, params)

    async def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        conn = await self._get_conn()
        cursor = await conn.execute(query, params)
        return await cursor.fetchone()

    async def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        conn = await self._get_conn()
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        return list(rows)

    async def commit(self) -> None:
        if self._conn:
            await self._conn.commit()

    async def execute_transaction(self, operations: list[tuple[str, tuple[Any, ...]]]) -> None:
        conn = await self._get_conn()
        try:
            await conn.execute("BEGIN")
            for query, params in operations:
                await conn.execute(query, params)
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise

    async def get_conversation(self, phone: str) -> Conversation | None:
        row = await self.fetchone(
            """SELECT phone, contact_name, state, last_message_at,
               requires_human_review, unread_count, sentiment_score, confidence, agent_id, current_session_id, created_at
               FROM conversations WHERE phone=?""",
            (phone,),
        )
        return row_to_conversation(row)

    async def get_all_conversations(self, limit: int = 100, offset: int = 0) -> list[Conversation]:
        rows = await self.fetchall(
            """SELECT phone, contact_name, state, last_message_at,
            requires_human_review, unread_count, sentiment_score, confidence, agent_id, current_session_id, created_at
            FROM conversations ORDER BY last_message_at DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        return [c for r in rows if (c := row_to_conversation(r)) is not None]

    async def get_messages(self, phone: str, limit: int = 100, desc: bool = False) -> list[Message]:
        order = "DESC" if desc else "ASC"
        rows = await self.fetchall(
            f"""SELECT id, phone, direction, source, text, media_type, media_url, meta_message_id, session_id, created_at
            FROM messages WHERE phone=? ORDER BY created_at {order} LIMIT ?""",
            (phone, limit),
        )
        return [m for r in rows if (m := row_to_message(r)) is not None]

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
        return [a for r in rows if (a := row_to_agent(r)) is not None]

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
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def activate_agent(self, agent_id: int) -> None:
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
            llm_escalate, escalate_reason, history_count, agent_name, correlation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                decision.correlation_id,
            ),
        )
        await conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def get_decisions(self, phone: str, limit: int = 50) -> list[AgentDecision]:
        rows = await self.fetchall(
            """SELECT ad.* FROM agent_decisions ad
            JOIN messages m ON ad.message_id = m.id
            WHERE m.phone = ?
            ORDER BY ad.created_at DESC LIMIT ?""",
            (phone, limit),
        )
        return [d for r in rows if (d := row_to_agent_decision(r)) is not None]

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

    async def upsert_memory(self, phone: str, summary: str, key_facts: str, total_count: int) -> None:
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
        from core.metrics import refresh_active_sessions
        await refresh_active_sessions(self)
        return session_id

    async def get_active_session(self, phone: str) -> Session | None:
        row = await self.fetchone(
            "SELECT * FROM sessions WHERE phone=? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            (phone,),
        )
        return row_to_session(row)

    async def close_session(self, session_id: str, reason: str, summary: str | None = None) -> None:
        conn = await self._get_conn()
        await conn.execute(
            "UPDATE sessions SET ended_at=CURRENT_TIMESTAMP, end_reason=?, summary=? WHERE id=?",
            (reason, summary, session_id),
        )
        await conn.commit()
        from core.metrics import refresh_active_sessions
        await refresh_active_sessions(self)

    async def insert_message(
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
        conn = await self._get_conn()
        cursor = await conn.execute(
            """INSERT INTO messages (phone, direction, source, text, media_type, media_url, meta_message_id, session_id, correlation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (phone, direction, source, text, media_type, media_url, meta_message_id, session_id, correlation_id),
        )
        await conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def save_order(self, phone: str, items_json: str, total: int) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO orders (phone, items_json, total, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
            items_json=excluded.items_json, total=excluded.total, updated_at=CURRENT_TIMESTAMP""",
            (phone, items_json, total),
        )
        await conn.commit()

    async def load_order(self, phone: str) -> tuple[str, int] | None:
        row = await self.fetchone(
            "SELECT items_json, total FROM orders WHERE phone=?",
            (phone,),
        )
        if row:
            return row["items_json"], row["total"]
        return None

    async def delete_order(self, phone: str) -> None:
        await self.execute("DELETE FROM orders WHERE phone=?", (phone,))

    async def escalate_conversation(
        self, phone: str, sentiment_score: float, confidence: float, reason: str
    ) -> None:
        await self.execute_transaction([
            (
                "UPDATE conversations SET sentiment_score=?, confidence=?, state='PENDING_APPROVAL', requires_human_review=1 WHERE phone=?",
                (sentiment_score, confidence, phone),
            ),
            (
                "INSERT INTO escalation_events (phone, from_state, to_state, reason, sentiment_score, confidence) VALUES (?, 'BOT_ACTIVE', 'PENDING_APPROVAL', ?, ?, ?)",
                (phone, reason, sentiment_score, confidence),
            ),
        ])

    async def update_conversation_sentiment(
        self, phone: str, sentiment_score: float, confidence: float
    ) -> None:
        await self.execute(
            "UPDATE conversations SET sentiment_score=?, confidence=? WHERE phone=?",
            (sentiment_score, confidence, phone),
        )

    async def increment_session_message_count(self, session_id: str) -> None:
        conn = await self._get_conn()
        await conn.execute(
            "UPDATE sessions SET message_count = message_count + 1 WHERE id=?", (session_id,)
        )
        await conn.commit()

    async def load_menu_items(self) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            "SELECT key, name, price, category, is_available, sort_order FROM menu_items ORDER BY sort_order"
        )
        return [dict(row) for row in rows]

    async def upsert_menu_item(
        self, key: str, name: str, price: int, category: str = "general", is_available: bool = True, sort_order: int = 0
    ) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO menu_items (key, name, price, category, is_available, sort_order, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
            name=excluded.name, price=excluded.price, category=excluded.category,
            is_available=excluded.is_available, sort_order=excluded.sort_order, updated_at=CURRENT_TIMESTAMP""",
            (key, name, price, category, int(is_available), sort_order),
        )
        await conn.commit()

    async def update_conversation_state(self, phone: str, state: str, requires_human_review: bool = False) -> None:
        await self.execute(
            "UPDATE conversations SET state=?, requires_human_review=? WHERE phone=?",
            (state, int(requires_human_review), phone),
        )
        await self.commit()

    async def reset_conversation_session(self, phone: str) -> None:
        await self.execute(
            "UPDATE conversations SET current_session_id=NULL, state='BOT_ACTIVE', requires_human_review=0 WHERE phone=?",
            (phone,),
        )
        await self.commit()

    async def set_conversation_agent(self, phone: str, agent_id: int) -> None:
        await self.execute(
            "UPDATE conversations SET agent_id=? WHERE phone=?", (agent_id, phone)
        )
        await self.commit()

    async def get_agent_capabilities(self, agent_id: int) -> list[AgentCapability]:
        rows = await self.fetchall(
            "SELECT * FROM agent_capabilities WHERE agent_id=? ORDER BY capability_name",
            (agent_id,),
        )
        return [c for r in rows if (c := row_to_agent_capability(r)) is not None]

    async def upsert_agent_capability(self, ac: AgentCapability) -> int:
        conn = await self._get_conn()
        cursor = await conn.execute(
            """INSERT INTO agent_capabilities (agent_id, capability_name, is_active, config_json, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(agent_id, capability_name) DO UPDATE SET
                is_active=excluded.is_active,
                config_json=excluded.config_json,
                updated_at=CURRENT_TIMESTAMP""",
            (ac.agent_id, ac.capability_name, ac.is_active, ac.config_json),
        )
        await conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def delete_agent_capability(self, agent_id: int, capability_name: str) -> None:
        await self.execute(
            "DELETE FROM agent_capabilities WHERE agent_id=? AND capability_name=?",
            (agent_id, capability_name),
        )
        await self.commit()

    async def save_appointment(self, phone: str, date: str, time: str, service_key: str, status: str = "confirmed") -> int:
        conn = await self._get_conn()
        cursor = await conn.execute(
            """INSERT INTO appointments (phone, date, time, service_key, status, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (phone, date, time, service_key, status),
        )
        await conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def load_appointments(self, phone: str, status: str = "confirmed") -> list[aiosqlite.Row]:
        if status:
            return await self.fetchall(
                "SELECT * FROM appointments WHERE phone=? AND status=? ORDER BY date, time",
                (phone, status),
            )
        return await self.fetchall(
            "SELECT * FROM appointments WHERE phone=? ORDER BY date, time",
            (phone,),
        )

    async def cancel_appointment(self, phone: str, date: str, time: str) -> None:
        conn = await self._get_conn()
        await conn.execute(
            "UPDATE appointments SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE phone=? AND date=? AND time=?",
            (phone, date, time),
        )
        await conn.commit()

    async def save_membership(self, phone: str, plan_key: str, status: str, started_at: str, next_billing: str) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO memberships (phone, plan_key, status, started_at, next_billing, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
            plan_key=excluded.plan_key, status=excluded.status,
            started_at=excluded.started_at, next_billing=excluded.next_billing, updated_at=CURRENT_TIMESTAMP""",
            (phone, plan_key, status, started_at, next_billing),
        )
        await conn.commit()

    async def load_membership(self, phone: str) -> aiosqlite.Row | None:
        return await self.fetchone(
            "SELECT * FROM memberships WHERE phone=?",
            (phone,),
        )

    async def cancel_membership(self, phone: str) -> None:
        conn = await self._get_conn()
        await conn.execute(
            "UPDATE memberships SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE phone=?",
            (phone,),
        )
        await conn.commit()

    async def load_plans(self) -> list[aiosqlite.Row]:
        return await self.fetchall(
            "SELECT * FROM plans ORDER BY sort_order, price"
        )

    async def upsert_plan(self, key: str, name: str, price: int, billing_cycle: str = "monthly", features: str = "[]", sort_order: int = 0) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO plans (key, name, price, billing_cycle, features, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
            name=excluded.name, price=excluded.price,
            billing_cycle=excluded.billing_cycle, features=excluded.features, sort_order=excluded.sort_order""",
            (key, name, price, billing_cycle, features, sort_order),
        )
        await conn.commit()

    async def load_lead(self, phone: str) -> aiosqlite.Row | None:
        return await self.fetchone(
            "SELECT * FROM leads WHERE phone=?",
            (phone,),
        )

    async def upsert_lead(self, phone: str, stage: str, data_json: str) -> None:
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO leads (phone, stage, data_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(phone) DO UPDATE SET
            stage=excluded.stage, data_json=excluded.data_json, updated_at=CURRENT_TIMESTAMP""",
            (phone, stage, data_json),
        )
        await conn.commit()

    async def insert_turn(self, turn: Turn) -> int:
        conn = await self._get_conn()
        cursor = await conn.execute(
            """INSERT INTO turns (phone, user_text, assistant_text, user_correlation_id, assistant_correlation_id, message_ids, session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (turn.phone, turn.user_text, turn.assistant_text, turn.user_correlation_id, turn.assistant_correlation_id, turn.message_ids, turn.session_id),
        )
        await conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def get_turns(self, phone: str, limit: int = 16, desc: bool = False) -> list[Turn]:
        order = "DESC" if desc else "ASC"
        rows = await self.fetchall(
            f"""SELECT id, phone, user_text, assistant_text, user_correlation_id, assistant_correlation_id, message_ids, session_id, created_at
            FROM turns WHERE phone=? ORDER BY id {order} LIMIT ?""",
            (phone, limit),
        )
        return [t for r in rows if (t := row_to_turn(r)) is not None]

    async def count_turns(self, phone: str) -> int:
        row = await self.fetchone(
            "SELECT COUNT(*) as cnt FROM turns WHERE phone=?",
            (phone,),
        )
        return row["cnt"] if row else 0

    async def get_last_turn(self, phone: str) -> Turn | None:
        row = await self.fetchone(
            """SELECT id, phone, user_text, assistant_text, user_correlation_id, assistant_correlation_id, message_ids, session_id, created_at
            FROM turns WHERE phone=? ORDER BY id DESC LIMIT 1""",
            (phone,),
        )
        return row_to_turn(row)

    async def get_turns_by_session(self, session_id: str) -> list[Turn]:
        rows = await self.fetchall(
            """SELECT id, phone, user_text, assistant_text, user_correlation_id, assistant_correlation_id, message_ids, session_id, created_at
            FROM turns WHERE session_id=? ORDER BY id ASC""",
            (session_id,),
        )
        return [t for r in rows if (t := row_to_turn(r)) is not None]

    async def get_session_summaries(self, phone: str, limit: int = 5) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """SELECT id, started_at, summary FROM sessions
            WHERE phone=? AND summary IS NOT NULL AND summary != ''
            ORDER BY started_at DESC LIMIT ?""",
            (phone, limit),
        )
        return [{"session_id": row["id"], "started_at": row["started_at"], "summary": row["summary"]} for row in rows]

    async def update_session_summary(self, session_id: str, summary: str) -> None:
        conn = await self._get_conn()
        await conn.execute(
            "UPDATE sessions SET summary=? WHERE id=?",
            (summary, session_id),
        )
        await conn.commit()

    async def insert_trace(self, trace: InferenceTrace) -> int:
        conn = await self._get_conn()
        cursor = await conn.execute(
            """INSERT INTO inference_traces
            (phone, correlation_id, agent_id, request_messages, response_raw,
            response_source, error_type, error_message, token_usage_prompt,
            token_usage_completion, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace.phone,
                trace.correlation_id,
                trace.agent_id,
                trace.request_messages,
                trace.response_raw,
                trace.response_source,
                trace.error_type,
                trace.error_message,
                trace.token_usage_prompt,
                trace.token_usage_completion,
                trace.latency_ms,
            ),
        )
        await conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def get_traces(self, phone: str, limit: int = 10) -> list[InferenceTrace]:
        rows = await self.fetchall(
            """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
            response_source, error_type, error_message, token_usage_prompt,
            token_usage_completion, latency_ms, created_at
            FROM inference_traces WHERE phone = ?
            ORDER BY created_at DESC LIMIT ?""",
            (phone, limit),
        )
        return [t for r in rows if (t := row_to_inference_trace(r)) is not None]

    async def get_trace_stats(self, hours: int = 24) -> dict[str, Any]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN response_source = 'llm' THEN 1 ELSE 0 END) as llm_count,
                SUM(CASE WHEN response_source = 'fallback' THEN 1 ELSE 0 END) as fallback_count,
                SUM(CASE WHEN response_source = 'error' THEN 1 ELSE 0 END) as error_count,
                ROUND(AVG(CASE WHEN response_source = 'llm' THEN latency_ms END)) as avg_llm_latency,
                ROUND(AVG(latency_ms)) as avg_latency
                FROM inference_traces
                WHERE created_at >= datetime('now', ?)""",
            (f"-{hours} hours",),
        )
        row = await cursor.fetchone()
        if row is None:
            return {"total": 0, "llm": 0, "fallback": 0, "error": 0, "avg_llm_latency": 0, "avg_latency": 0}
        return {
            "total": row[0] or 0,
            "llm": row[1] or 0,
            "fallback": row[2] or 0,
            "error": row[3] or 0,
            "avg_llm_latency": row[4] or 0,
            "avg_latency": row[5] or 0,
        }

    async def get_last_error(self) -> dict[str, Any] | None:
        rows = await self.fetchall(
            """SELECT id, phone, correlation_id, error_type, error_message, created_at
            FROM inference_traces
            WHERE response_source = 'error'
            ORDER BY created_at DESC LIMIT 1""",
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0],
            "phone": r[1],
            "correlation_id": r[2],
            "error_type": r[3],
            "error_message": r[4],
            "created_at": r[5],
        }

    async def get_recent_traces(self, limit: int = 50, source: str | None = None) -> list[InferenceTrace]:
        if source:
            rows = await self.fetchall(
                """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
                          response_source, error_type, error_message,
                          token_usage_prompt, token_usage_completion, latency_ms, created_at
                   FROM inference_traces
                   WHERE response_source = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (source, limit),
            )
        else:
            rows = await self.fetchall(
                """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
                          response_source, error_type, error_message,
                          token_usage_prompt, token_usage_completion, latency_ms, created_at
                   FROM inference_traces
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            )
        return [t for r in rows if (t := row_to_inference_trace(r)) is not None]

    async def get_trace_by_id(self, trace_id: int) -> InferenceTrace | None:
        row = await self.fetchone(
            """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
                      response_source, error_type, error_message,
                      token_usage_prompt, token_usage_completion, latency_ms, created_at
               FROM inference_traces WHERE id = ?""",
            (trace_id,),
        )
        return row_to_inference_trace(row)

    async def cleanup_traces(self, days: int = 30) -> int:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "DELETE FROM inference_traces WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        await conn.commit()
        return cursor.rowcount

    async def get_all_templates(self) -> list[AgentTemplate]:
        rows = await self.fetchall(
            "SELECT id, name, description, system_prompt_template, capabilities, fallback_responses, created_at FROM agent_templates ORDER BY id"
        )
        return [t for r in rows if (t := row_to_agent_template(r)) is not None]

    async def get_template(self, template_id: int) -> AgentTemplate | None:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT id, name, description, system_prompt_template, capabilities, fallback_responses, created_at FROM agent_templates WHERE id = ?",
            (template_id,),
        )
        row = await cursor.fetchone()
        return row_to_agent_template(row)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None


db = Database()


async def init_db() -> None:
    from db.migrator import run_migrations
    os.makedirs(settings.DB_DIR, exist_ok=True)
    run_migrations(settings.DB_PATH)
    await db._get_conn()


async def get_db() -> Database:
    return db


async def close_db() -> None:
    await db.close()

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
)
from db.repositories.agent import (
    AgentCapabilityRepository,
    AgentDecisionRepository,
    AgentRepository,
    AgentTemplateRepository,
)
from db.repositories.business import (
    AppointmentRepository,
    LeadRepository,
    MembershipRepository,
    MenuRepository,
    OrderRepository,
    PlanRepository,
)
from db.repositories.conversation import ConversationRepository, MessageRepository
from db.repositories.memory import MemoryRepository
from db.repositories.session import SessionRepository, TurnRepository
from db.repositories.trace import TraceRepository

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None
        self._init_lock = asyncio.Lock()

        self.conversations = ConversationRepository(self._get_conn)
        self.messages = MessageRepository(self._get_conn)
        self.agents = AgentRepository(self._get_conn)
        self.agent_decisions = AgentDecisionRepository(self._get_conn)
        self.agent_capabilities = AgentCapabilityRepository(self._get_conn)
        self.agent_templates = AgentTemplateRepository(self._get_conn)
        self.memory = MemoryRepository(self._get_conn)
        self.sessions = SessionRepository(self._get_conn)
        self.turns = TurnRepository(self._get_conn)
        self.traces = TraceRepository(self._get_conn)
        self.orders = OrderRepository(self._get_conn)
        self.menus = MenuRepository(self._get_conn)
        self.appointments = AppointmentRepository(self._get_conn)
        self.memberships = MembershipRepository(self._get_conn)
        self.plans = PlanRepository(self._get_conn)
        self.leads = LeadRepository(self._get_conn)

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

    # -----------------------------------------------------------------------
    # BACKWARD-COMPATIBLE DELEGATES
    # All legacy method signatures are preserved. Each delegates to the
    # appropriate repository so callers don't need to change yet.
    # -----------------------------------------------------------------------

    async def get_conversation(self, phone: str) -> Conversation | None:
        return await self.conversations.get(phone)

    async def create_conversation(self, phone: str, agent_id: int = 1) -> None:
        return await self.conversations.create(phone, agent_id)

    async def get_all_conversations(self, limit: int = 100, offset: int = 0) -> list[Conversation]:
        return await self.conversations.get_all(limit, offset)

    async def get_messages(self, phone: str, limit: int = 100, desc: bool = False) -> list[Message]:
        return await self.messages.get(phone, limit, desc)

    async def get_agent(self, agent_id: int | None = None, is_active: bool = True) -> Agent | None:
        return await self.agents.get(agent_id, is_active)

    async def get_all_agents(self) -> list[Agent]:
        return await self.agents.get_all()

    async def upsert_agent(self, agent: Agent) -> int:
        return await self.agents.upsert(agent)

    async def activate_agent(self, agent_id: int) -> None:
        return await self.agents.activate(agent_id)

    async def insert_agent_decision(self, decision: AgentDecision) -> int:
        return await self.agent_decisions.insert(decision)

    async def get_decisions(self, phone: str, limit: int = 50) -> list[AgentDecision]:
        return await self.agent_decisions.get_for_phone(phone, limit)

    async def get_decision_for_message(self, message_id: int) -> AgentDecision | None:
        return await self.agent_decisions.get_for_message(message_id)

    async def get_memory(self, phone: str) -> ConversationMemory | None:
        return await self.memory.get(phone)

    async def upsert_memory(self, phone: str, summary: str, key_facts: str, total_count: int) -> None:
        return await self.memory.upsert(phone, summary, key_facts, total_count)

    async def count_messages(self, phone: str) -> int:
        return await self.messages.count(phone)

    async def create_session(self, phone: str) -> str:
        return await self.sessions.create(phone)

    async def get_active_session(self, phone: str) -> Session | None:
        return await self.sessions.get_active(phone)

    async def close_session(self, session_id: str, reason: str, summary: str | None = None) -> None:
        return await self.sessions.close(session_id, reason, summary)

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
        return await self.messages.insert(
            phone, direction, source, text, session_id, media_type, media_url, meta_message_id, correlation_id,
        )

    async def save_order(self, phone: str, items_json: str, total: int) -> None:
        return await self.orders.save(phone, items_json, total)

    async def load_order(self, phone: str) -> tuple[str, int] | None:
        return await self.orders.load(phone)

    async def delete_order(self, phone: str) -> None:
        return await self.orders.delete(phone)

    async def escalate_conversation(
        self, phone: str, sentiment_score: float, confidence: float, reason: str
    ) -> None:
        return await self.conversations.escalate(phone, sentiment_score, confidence, reason)

    async def update_conversation_sentiment(
        self, phone: str, sentiment_score: float, confidence: float
    ) -> None:
        return await self.conversations.update_sentiment(phone, sentiment_score, confidence)

    async def increment_session_message_count(self, session_id: str) -> None:
        return await self.sessions.increment_message_count(session_id)

    async def load_menu_items(self) -> list[dict[str, Any]]:
        return await self.menus.load_items()

    async def upsert_menu_item(
        self, key: str, name: str, price: int, category: str = "general", is_available: bool = True, sort_order: int = 0
    ) -> None:
        return await self.menus.upsert_item(key, name, price, category, is_available, sort_order)

    async def update_conversation_state(self, phone: str, state: str, requires_human_review: bool = False) -> None:
        return await self.conversations.update_state(phone, state, requires_human_review)

    async def reset_conversation_session(self, phone: str) -> None:
        return await self.conversations.reset_session(phone)

    async def set_conversation_agent(self, phone: str, agent_id: int) -> None:
        return await self.conversations.set_agent(phone, agent_id)

    async def get_agent_capabilities(self, agent_id: int) -> list[AgentCapability]:
        return await self.agent_capabilities.get_for_agent(agent_id)

    async def upsert_agent_capability(self, ac: AgentCapability) -> int:
        return await self.agent_capabilities.upsert(ac)

    async def delete_agent_capability(self, agent_id: int, capability_name: str) -> None:
        return await self.agent_capabilities.delete(agent_id, capability_name)

    async def save_appointment(self, phone: str, date: str, time: str, service_key: str, status: str = "confirmed") -> int:
        return await self.appointments.save(phone, date, time, service_key, status)

    async def load_appointments(self, phone: str, status: str = "confirmed") -> list[aiosqlite.Row]:
        return await self.appointments.load(phone, status)

    async def cancel_appointment(self, phone: str, date: str, time: str) -> None:
        return await self.appointments.cancel(phone, date, time)

    async def save_membership(self, phone: str, plan_key: str, status: str, started_at: str, next_billing: str) -> None:
        return await self.memberships.save(phone, plan_key, status, started_at, next_billing)

    async def load_membership(self, phone: str) -> aiosqlite.Row | None:
        return await self.memberships.load(phone)

    async def cancel_membership(self, phone: str) -> None:
        return await self.memberships.cancel(phone)

    async def load_plans(self) -> list[aiosqlite.Row]:
        return await self.plans.load_all()

    async def upsert_plan(self, key: str, name: str, price: int, billing_cycle: str = "monthly", features: str = "[]", sort_order: int = 0) -> None:
        return await self.plans.upsert(key, name, price, billing_cycle, features, sort_order)

    async def load_lead(self, phone: str) -> aiosqlite.Row | None:
        return await self.leads.load(phone)

    async def upsert_lead(self, phone: str, stage: str, data_json: str) -> None:
        return await self.leads.upsert(phone, stage, data_json)

    async def insert_turn(self, turn: Turn) -> int:
        return await self.turns.insert(turn)

    async def get_turns(self, phone: str, limit: int = 16, desc: bool = False) -> list[Turn]:
        return await self.turns.get(phone, limit, desc)

    async def count_turns(self, phone: str) -> int:
        return await self.turns.count(phone)

    async def get_last_turn(self, phone: str) -> Turn | None:
        return await self.turns.get_last(phone)

    async def get_turns_by_session(self, session_id: str) -> list[Turn]:
        return await self.turns.get_by_session(session_id)

    async def get_session_summaries(self, phone: str, limit: int = 5) -> list[dict[str, Any]]:
        return await self.sessions.get_summaries(phone, limit)

    async def update_session_summary(self, session_id: str, summary: str) -> None:
        return await self.sessions.update_summary(session_id, summary)

    async def insert_trace(self, trace: InferenceTrace) -> int:
        return await self.traces.insert(trace)

    async def get_traces(self, phone: str, limit: int = 10) -> list[InferenceTrace]:
        return await self.traces.get_for_phone(phone, limit)

    async def get_trace_stats(self, hours: int = 24) -> dict[str, Any]:
        return await self.traces.get_stats(hours)

    async def get_last_error(self) -> dict[str, Any] | None:
        return await self.traces.get_last_error()

    async def get_recent_traces(self, limit: int = 50, source: str | None = None) -> list[InferenceTrace]:
        return await self.traces.get_recent(limit, source)

    async def get_trace_by_id(self, trace_id: int) -> InferenceTrace | None:
        return await self.traces.get_by_id(trace_id)

    async def cleanup_traces(self, days: int = 30) -> int:
        return await self.traces.cleanup(days)

    async def get_all_templates(self) -> list[AgentTemplate]:
        return await self.agent_templates.get_all()

    async def get_template(self, template_id: int) -> AgentTemplate | None:
        return await self.agent_templates.get(template_id)

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

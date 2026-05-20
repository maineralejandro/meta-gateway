from pathlib import Path
from typing import Any

import asyncpg
import structlog

from core.config import settings
from db.engine import close_pool, create_pool, get_pool
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
    CartRepository,
    CatalogRepository,
    LeadRepository,
    MembershipRepository,
    OptionRepository,
    PlanRepository,
    PromotionRepository,
    VariantRepository,
)
from db.repositories.conversation import ConversationRepository, MessageRepository
from db.repositories.memory import MemoryRepository
from db.repositories.session import SessionRepository, TurnRepository
from db.repositories.trace import TraceRepository

logger = structlog.get_logger()


class Database:
    def __init__(self) -> None:
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()
        self.agents = AgentRepository()
        self.agent_decisions = AgentDecisionRepository()
        self.agent_capabilities = AgentCapabilityRepository()
        self.agent_templates = AgentTemplateRepository()
        self.memory = MemoryRepository()
        self.sessions = SessionRepository()
        self.turns = TurnRepository()
        self.traces = TraceRepository()
        self.carts = CartRepository()
        self.catalog = CatalogRepository()
        self.variants = VariantRepository()
        self.options = OptionRepository()
        self.promotions = PromotionRepository()
        self.appointments = AppointmentRepository()
        self.memberships = MembershipRepository()
        self.plans = PlanRepository()
        self.leads = LeadRepository()

    async def execute(self, query: str, *args: Any) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(query, *args)

    async def executemany(self, query: str, params: list[tuple[Any, ...]]) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.executemany(query, params)

    async def fetchone(self, query: str, *args: Any) -> asyncpg.Record | None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchall(self, query: str, *args: Any) -> list[asyncpg.Record]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)  # type: ignore[no-any-return]

    async def commit(self) -> None:
        pass

    async def execute_transaction(self, operations: list[tuple[str, tuple[Any, ...]]]) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            for query, args in operations:
                await conn.execute(query, *args)

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

    async def get_or_create_session_atomic(self, phone: str) -> str:
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT state, current_session_id, last_message_at, agent_id FROM conversations WHERE phone=$1 FOR UPDATE",
                phone,
            )
            if not row:
                import uuid
                session_id = str(uuid.uuid4())
                await conn.execute(
                    "INSERT INTO conversations (phone, state, agent_id, last_message_at) VALUES ($1, 'BOT_ACTIVE', 1, NOW())",
                    phone,
                )
                await conn.execute(
                    "INSERT INTO sessions (id, phone) VALUES ($1, $2)",
                    session_id, phone,
                )
                await conn.execute(
                    "UPDATE conversations SET current_session_id=$1 WHERE phone=$2",
                    session_id, phone,
                )
                return session_id

            if not row["current_session_id"]:
                import uuid
                session_id = str(uuid.uuid4())
                await conn.execute(
                    "INSERT INTO sessions (id, phone) VALUES ($1, $2)",
                    session_id, phone,
                )
                await conn.execute(
                    "UPDATE conversations SET current_session_id=$1 WHERE phone=$2",
                    session_id, phone,
                )
                return session_id

            return str(row["current_session_id"])

    async def expire_and_create_session_atomic(
        self, phone: str, old_session_id: str, agent_id: int | None, new_state: str | None = None
    ) -> str:
        import uuid
        session_id = str(uuid.uuid4())
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.fetchrow(
                "SELECT phone FROM conversations WHERE phone=$1 FOR UPDATE",
                phone,
            )
            await conn.execute(
                "UPDATE sessions SET ended_at=NOW(), end_reason=$1 WHERE id=$2",
                "timeout", old_session_id,
            )
            if new_state and new_state != "BOT_ACTIVE":
                await conn.execute(
                    "UPDATE conversations SET state='BOT_ACTIVE', requires_human_review=FALSE WHERE phone=$1",
                    phone,
                )
            await conn.execute(
                "INSERT INTO sessions (id, phone) VALUES ($1, $2)",
                session_id, phone,
            )
            await conn.execute(
                "UPDATE conversations SET current_session_id=$1 WHERE phone=$2",
                session_id, phone,
            )
        return session_id

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

    async def insert_message_and_touch_conversation(
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
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO messages (phone, direction, source, text, media_type, media_url, meta_message_id, session_id, correlation_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id""",
                phone, direction, source, text,
                media_type, media_url, meta_message_id, session_id, correlation_id,
            )
            message_id = row["id"]
            await conn.execute(
                "UPDATE conversations SET last_message_at=NOW(), unread_count=unread_count+1 WHERE phone=$1",
                phone,
            )
            return int(message_id)

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

    async def load_catalog_items(self) -> list[dict[str, Any]]:
        return await self.catalog.load_items()

    async def upsert_catalog_item(
        self, key: str, name: str, price: int, category: str = "general",
        is_available: bool = True, sort_order: int = 0,
        description: str = "", tags: str = "[]", size: str = "",
        specifications: str = "",
        subcategory: str = "", base_price: int | None = None,
    ) -> None:
        return await self.catalog.upsert_item(
            key, name, price, category, is_available, sort_order,
            description, tags, size, specifications,
            subcategory, base_price,
        )

    async def load_catalog_variants(self) -> list[dict[str, Any]]:
        return await self.variants.load_all()

    async def load_catalog_variants_for_item(self, item_key: str) -> list[dict[str, Any]]:
        return await self.variants.load_for_item(item_key)

    async def upsert_catalog_variant(self, item_key: str, label: str, price: int, slug: str, sort_order: int = 0) -> None:
        return await self.variants.upsert(item_key, label, price, slug, sort_order)

    async def delete_catalog_variants_for_item(self, item_key: str) -> None:
        return await self.variants.delete_for_item(item_key)

    async def load_catalog_options(self) -> list[dict[str, Any]]:
        return await self.options.load_all()

    async def load_catalog_options_for_category(self, category: str) -> list[dict[str, Any]]:
        return await self.options.load_for_category(category)

    async def upsert_catalog_option(self, key: str, name: str, price: int, category_scope: str = "", sort_order: int = 0) -> None:
        return await self.options.upsert(key, name, price, category_scope, sort_order)

    async def delete_catalog_option(self, key: str) -> None:
        return await self.options.delete(key)

    async def load_promotions(self) -> list[dict[str, Any]]:
        return await self.promotions.load_all()

    async def upsert_promotion(
        self, key: str, name: str, promotion_type: str, price: int | None = None,
        valid_days: str = "[]", valid_from: str = "", valid_to: str = "",
        terms: str = "", display_text: str = "", sort_order: int = 0,
    ) -> None:
        return await self.promotions.upsert(
            key, name, promotion_type, price, valid_days, valid_from, valid_to,
            terms, display_text, sort_order,
        )

    async def load_promotion_items(self, promotion_key: str) -> list[dict[str, Any]]:
        return await self.promotions.load_promotion_items(promotion_key)

    async def upsert_promotion_item(self, promotion_key: str, item_key: str, promotion_price: int | None = None) -> None:
        return await self.promotions.upsert_promotion_item(promotion_key, item_key, promotion_price)

    async def delete_promotion_items(self, promotion_key: str) -> None:
        return await self.promotions.delete_promotion_items(promotion_key)

    async def delete_promotion(self, key: str) -> None:
        return await self.promotions.delete(key)

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

    async def load_appointments(self, phone: str, status: str = "confirmed") -> list[asyncpg.Record]:
        return await self.appointments.load(phone, status)

    async def cancel_appointment(self, phone: str, date: str, time: str) -> None:
        return await self.appointments.cancel(phone, date, time)

    async def save_membership(self, phone: str, plan_key: str, status: str, started_at: str, next_billing: str) -> None:
        return await self.memberships.save(phone, plan_key, status, started_at, next_billing)

    async def load_membership(self, phone: str) -> asyncpg.Record | None:
        return await self.memberships.load(phone)

    async def cancel_membership(self, phone: str) -> None:
        return await self.memberships.cancel(phone)

    async def load_plans(self) -> list[asyncpg.Record]:
        return await self.plans.load_all()

    async def upsert_plan(self, key: str, name: str, price: int, billing_cycle: str = "monthly", features: str = "[]", sort_order: int = 0) -> None:
        return await self.plans.upsert(key, name, price, billing_cycle, features, sort_order)

    async def load_lead(self, phone: str) -> asyncpg.Record | None:
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

    async def close_session_and_reset(self, phone: str, reason: str, summary: str | None = None) -> str | None:
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT current_session_id FROM conversations WHERE phone=$1 FOR UPDATE",
                phone,
            )
            if not row or not row["current_session_id"]:
                return None
            session_id = row["current_session_id"]
            await conn.execute(
                "UPDATE sessions SET ended_at=NOW(), end_reason=$1, summary=$2 WHERE id=$3",
                reason, summary, session_id,
            )
            await conn.execute(
                "UPDATE conversations SET current_session_id=NULL, state='BOT_ACTIVE', requires_human_review=FALSE WHERE phone=$1",
                phone,
            )
            return str(session_id)

    async def update_state_atomic(self, phone: str, new_state: str) -> dict[str, str]:
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT state FROM conversations WHERE phone=$1 FOR UPDATE",
                phone,
            )
            old_state = row["state"] if row else "BOT_ACTIVE"

            if not row:
                await conn.execute(
                    "INSERT INTO conversations (phone, state, last_message_at) VALUES ($1, $2, NOW())",
                    phone, new_state,
                )
            else:
                await conn.execute(
                    "UPDATE conversations SET state=$1, requires_human_review=$2 WHERE phone=$3",
                    new_state, new_state != "BOT_ACTIVE", phone,
                )

            if old_state != new_state:
                await conn.execute(
                    "INSERT INTO escalation_events (phone, from_state, to_state, reason) VALUES ($1, $2, $3, $4)",
                    phone, old_state, new_state, "manual_change",
                )
        return {"old_state": old_state, "new_state": new_state}

    async def close(self) -> None:
        await close_pool()


db = Database()


async def init_db() -> None:
    import logging

    logging.getLogger("alembic").setLevel(logging.WARNING)
    logging.getLogger("alembic.runtime.migration").setLevel(logging.WARNING)

    from alembic import command # noqa: I001
    from alembic.config import Config as AlembicConfig

    alembic_cfg = AlembicConfig()
    alembic_cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    command.upgrade(alembic_cfg, "head")
    logger.info("alembic_upgraded", url=settings.DATABASE_URL.split("@")[-1])

    await create_pool()
    logger.info("db_initialized", engine="postgresql")


async def get_db() -> Database:
    return db


async def close_db() -> None:
    await db.close()

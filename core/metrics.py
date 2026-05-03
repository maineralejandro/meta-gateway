from typing import Any

import structlog
from prometheus_client import Counter, Gauge, Histogram, Info

logger = structlog.get_logger()

MESSAGES_RECEIVED = Counter(
    "hermes_messages_received_total",
    "Total inbound messages received from WhatsApp",
    ["source"],
)

MESSAGES_SENT = Counter(
    "hermes_messages_sent_total",
    "Total outbound messages sent via WhatsApp",
    ["source"],
)

ESCALATIONS = Counter(
    "hermes_escalations_total",
    "Total conversation escalations",
    ["reason"],
)

LLM_REQUESTS = Counter(
    "hermes_llm_requests_total",
    "Total LLM inference requests",
)

LLM_ERRORS = Counter(
    "hermes_llm_errors_total",
    "Total LLM inference errors",
)

LLM_LATENCY = Histogram(
    "hermes_llm_latency_seconds",
    "LLM inference latency in seconds",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

LLM_TOKENS_PROMPT = Counter(
    "hermes_llm_tokens_prompt_total",
    "Total prompt tokens sent to LLM",
)

LLM_TOKENS_COMPLETION = Counter(
    "hermes_llm_tokens_completion_total",
    "Total completion tokens received from LLM",
)

WEBHOOK_DUPLICATES = Counter(
    "hermes_webhook_duplicates_total",
    "Total duplicate webhook messages ignored",
)

RATE_LIMITS = Counter(
    "hermes_rate_limits_total",
    "Total messages rejected by rate limiter",
)

ACTIVE_CONVERSATIONS = Gauge(
    "hermes_active_conversations",
    "Number of conversations in non-BOT_ACTIVE states",
)

ACTIVE_SESSIONS = Gauge(
    "hermes_active_sessions",
    "Number of open sessions",
)

APP_INFO = Info(
    "hermes",
    "Hermes WhatsApp HITL Gateway",
)


async def refresh_active_conversations(db: Any = None) -> None:
    try:
        if db is None:
            from db.database import get_db
            db = await get_db()
        row = await db.fetchone(
            "SELECT COUNT(*) FROM conversations WHERE state != 'BOT_ACTIVE'"
        )
        ACTIVE_CONVERSATIONS.set(row[0] if row else 0)
    except Exception as e:
        logger.warning("metrics_refresh_failed", metric="active_conversations", error=str(e))


async def refresh_active_sessions(db: Any = None) -> None:
    try:
        if db is None:
            from db.database import get_db
            db = await get_db()
        row = await db.fetchone(
            "SELECT COUNT(*) FROM sessions WHERE ended_at IS NULL"
        )
        ACTIVE_SESSIONS.set(row[0] if row else 0)
    except Exception as e:
        logger.warning("metrics_refresh_failed", metric="active_sessions", error=str(e))

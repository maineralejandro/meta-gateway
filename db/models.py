from dataclasses import dataclass
from typing import Any

import asyncpg


@dataclass
class Agent:
    id: int | None = None
    name: str = ""
    description: str = ""
    system_prompt: str = ""
    escalation_marker: str = "ESCALATE_TO_HUMAN"
    fallback_responses: str = "{}"
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class Session:
    id: str
    phone: str
    started_at: str | None = None
    ended_at: str | None = None
    end_reason: str | None = None
    summary: str | None = None
    message_count: int = 0


@dataclass
class Conversation:
    phone: str
    contact_name: str | None = None
    state: str = "BOT_ACTIVE"
    last_message_at: str | None = None
    requires_human_review: bool = False
    unread_count: int = 0
    sentiment_score: float | None = None
    confidence: float | None = None
    agent_id: int | None = 1
    current_session_id: str | None = None
    created_at: str | None = None


@dataclass
class Message:
    id: int
    phone: str
    direction: str
    source: str
    text: str | None = None
    media_type: str | None = None
    media_url: str | None = None
    meta_message_id: str | None = None
    session_id: str | None = None
    correlation_id: str | None = None
    created_at: str | None = None


@dataclass
class EscalationEvent:
    id: int = 0
    phone: str = ""
    from_state: str = ""
    to_state: str = ""
    reason: str | None = None
    sentiment_score: float | None = None
    confidence: float | None = None
    created_at: str | None = None


@dataclass
class AgentDecision:
    id: int | None = None
    message_id: int | None = None
    phone: str = ""
    sentiment: str = "neutral"
    sentiment_score: float = 0.5
    confidence: float = 0.5
    llm_escalate: bool = False
    escalate_reason: str | None = None
    history_count: int = 0
    agent_name: str = ""
    correlation_id: str | None = None
    created_at: str | None = None


@dataclass
class ConversationMemory:
    phone: str
    summary: str = ""
    key_facts: str = "[]"
    total_messages_summarized: int = 0
    updated_at: str | None = None


@dataclass
class AgentCapability:
    id: int | None = None
    agent_id: int = 0
    capability_name: str = ""
    is_active: bool = True
    config_json: str = "{}"
    created_at: str | None = None
    updated_at: str | None = None


def _val(row: asyncpg.Record | dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def row_to_agent(row: asyncpg.Record | dict[str, Any] | None) -> Agent | None:
    if row is None:
        return None
    return Agent(
        id=_val(row, "id"),
        name=_val(row, "name", ""),
        description=_val(row, "description", ""),
        system_prompt=_val(row, "system_prompt", ""),
        escalation_marker=_val(row, "escalation_marker", "ESCALATE_TO_HUMAN"),
        fallback_responses=_val(row, "fallback_responses", "{}"),
        is_active=_val(row, "is_active", True),
        created_at=_val(row, "created_at"),
        updated_at=_val(row, "updated_at"),
    )


def row_to_conversation(row: asyncpg.Record | dict[str, Any] | None) -> Conversation | None:
    if row is None:
        return None
    return Conversation(
        phone=_val(row, "phone", ""),
        contact_name=_val(row, "contact_name"),
        state=_val(row, "state", "BOT_ACTIVE"),
        last_message_at=_val(row, "last_message_at"),
        requires_human_review=_val(row, "requires_human_review", False),
        unread_count=_val(row, "unread_count", 0),
        sentiment_score=_val(row, "sentiment_score"),
        confidence=_val(row, "confidence"),
        agent_id=_val(row, "agent_id", 1),
        current_session_id=_val(row, "current_session_id"),
        created_at=_val(row, "created_at"),
    )


def row_to_message(row: asyncpg.Record | dict[str, Any] | None) -> Message | None:
    if row is None:
        return None
    return Message(
        id=_val(row, "id", 0),
        phone=_val(row, "phone", ""),
        direction=_val(row, "direction", ""),
        source=_val(row, "source", ""),
        text=_val(row, "text"),
        media_type=_val(row, "media_type"),
        media_url=_val(row, "media_url"),
        meta_message_id=_val(row, "meta_message_id"),
        session_id=_val(row, "session_id"),
        correlation_id=_val(row, "correlation_id"),
        created_at=_val(row, "created_at"),
    )


def row_to_session(row: asyncpg.Record | dict[str, Any] | None) -> Session | None:
    if row is None:
        return None
    return Session(
        id=_val(row, "id", ""),
        phone=_val(row, "phone", ""),
        started_at=_val(row, "started_at"),
        ended_at=_val(row, "ended_at"),
        end_reason=_val(row, "end_reason"),
        summary=_val(row, "summary"),
        message_count=_val(row, "message_count", 0),
    )


def row_to_agent_decision(row: asyncpg.Record | dict[str, Any] | None) -> AgentDecision | None:
    if row is None:
        return None
    return AgentDecision(
        id=_val(row, "id"),
        message_id=_val(row, "message_id"),
        phone=_val(row, "phone", ""),
        sentiment=_val(row, "sentiment", "neutral"),
        sentiment_score=_val(row, "sentiment_score", 0.5),
        confidence=_val(row, "confidence", 0.5),
        llm_escalate=_val(row, "llm_escalate", False),
        escalate_reason=_val(row, "escalate_reason"),
        history_count=_val(row, "history_count", 0),
        agent_name=_val(row, "agent_name", ""),
        correlation_id=_val(row, "correlation_id"),
        created_at=_val(row, "created_at"),
    )


def row_to_memory(row: asyncpg.Record | dict[str, Any] | None) -> ConversationMemory | None:
    if row is None:
        return None
    return ConversationMemory(
        phone=_val(row, "phone", ""),
        summary=_val(row, "summary", ""),
        key_facts=_val(row, "key_facts", "[]"),
        total_messages_summarized=_val(row, "total_messages_summarized", 0),
        updated_at=_val(row, "updated_at"),
    )


def row_to_agent_capability(row: asyncpg.Record | dict[str, Any] | None) -> AgentCapability | None:
    if row is None:
        return None
    return AgentCapability(
        id=_val(row, "id"),
        agent_id=_val(row, "agent_id", 0),
        capability_name=_val(row, "capability_name", ""),
        is_active=_val(row, "is_active", True),
        config_json=_val(row, "config_json", "{}"),
        created_at=_val(row, "created_at"),
        updated_at=_val(row, "updated_at"),
    )


@dataclass
class AgentTemplate:
    id: int | None = None
    name: str = ""
    description: str = ""
    system_prompt_template: str = ""
    capabilities: str = "[]"
    fallback_responses: str = "{}"
    created_at: str | None = None


def row_to_agent_template(row: asyncpg.Record | dict[str, Any] | None) -> AgentTemplate | None:
    if row is None:
        return None
    return AgentTemplate(
        id=_val(row, "id"),
        name=_val(row, "name", ""),
        description=_val(row, "description", ""),
        system_prompt_template=_val(row, "system_prompt_template", ""),
        capabilities=_val(row, "capabilities", "[]"),
        fallback_responses=_val(row, "fallback_responses", "{}"),
        created_at=_val(row, "created_at"),
    )


@dataclass
class Turn:
    id: int | None = None
    phone: str = ""
    user_text: str = ""
    assistant_text: str = ""
    user_correlation_id: str | None = None
    assistant_correlation_id: str | None = None
    message_ids: str = "[]"
    session_id: str | None = None
    created_at: str | None = None


def row_to_turn(row: asyncpg.Record | dict[str, Any] | None) -> Turn | None:
    if row is None:
        return None
    return Turn(
        id=_val(row, "id"),
        phone=_val(row, "phone", ""),
        user_text=_val(row, "user_text", ""),
        assistant_text=_val(row, "assistant_text", ""),
        user_correlation_id=_val(row, "user_correlation_id"),
        assistant_correlation_id=_val(row, "assistant_correlation_id"),
        message_ids=_val(row, "message_ids", "[]"),
        session_id=_val(row, "session_id"),
        created_at=_val(row, "created_at"),
    )


@dataclass
class InferenceTrace:
    id: int | None = None
    phone: str = ""
    correlation_id: str = ""
    agent_id: int | None = None
    request_messages: str = ""
    response_raw: str | None = None
    response_source: str = ""
    error_type: str | None = None
    error_message: str | None = None
    token_usage_prompt: int = 0
    token_usage_completion: int = 0
    latency_ms: int = 0
    created_at: str | None = None


def row_to_inference_trace(row: asyncpg.Record | dict[str, Any] | None) -> InferenceTrace | None:
    if row is None:
        return None
    return InferenceTrace(
        id=_val(row, "id"),
        phone=_val(row, "phone", ""),
        correlation_id=_val(row, "correlation_id", ""),
        agent_id=_val(row, "agent_id"),
        request_messages=_val(row, "request_messages", ""),
        response_raw=_val(row, "response_raw"),
        response_source=_val(row, "response_source", ""),
        error_type=_val(row, "error_type"),
        error_message=_val(row, "error_message"),
        token_usage_prompt=_val(row, "token_usage_prompt", 0),
        token_usage_completion=_val(row, "token_usage_completion", 0),
        latency_ms=_val(row, "latency_ms", 0),
        created_at=_val(row, "created_at"),
    )


@dataclass
class WhatsAppTemplate:
    id: int | None = None
    agent_id: int = 1
    template_name: str = ""
    template_type: str = "UTILITY"
    category: str = "UTILITY"
    language: str = "es"
    status: str = "PENDING"
    body_text: str = ""
    header_text: str | None = None
    header_image_url: str | None = None
    footer_text: str | None = None
    buttons_json: str = "[]"
    meta_template_id: str | None = None
    meta_quality_rating: str | None = None
    rejection_reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


def row_to_whatsapp_template(row: asyncpg.Record | dict[str, Any] | None) -> WhatsAppTemplate | None:
    if row is None:
        return None
    return WhatsAppTemplate(
        id=_val(row, "id"),
        agent_id=_val(row, "agent_id", 1),
        template_name=_val(row, "template_name", ""),
        template_type=_val(row, "template_type", "UTILITY"),
        category=_val(row, "category", "UTILITY"),
        language=_val(row, "language", "es"),
        status=_val(row, "status", "PENDING"),
        body_text=_val(row, "body_text", ""),
        header_text=_val(row, "header_text"),
        header_image_url=_val(row, "header_image_url"),
        footer_text=_val(row, "footer_text"),
        buttons_json=_val(row, "buttons_json", "[]"),
        meta_template_id=_val(row, "meta_template_id"),
        meta_quality_rating=_val(row, "meta_quality_rating"),
        rejection_reason=_val(row, "rejection_reason"),
        created_at=_val(row, "created_at"),
        updated_at=_val(row, "updated_at"),
    )


@dataclass
class ScheduledMessage:
    id: int | None = None
    phone: str = ""
    template_name: str = ""
    components_json: str = "[]"
    scheduled_at: str | None = None
    triggered_by_message_id: str | None = None
    status: str = "PENDING"
    sent_at: str | None = None
    created_at: str | None = None


def row_to_scheduled_message(row: asyncpg.Record | dict[str, Any] | None) -> ScheduledMessage | None:
    if row is None:
        return None
    return ScheduledMessage(
        id=_val(row, "id"),
        phone=_val(row, "phone", ""),
        template_name=_val(row, "template_name", ""),
        components_json=_val(row, "components_json", "[]"),
        scheduled_at=_val(row, "scheduled_at"),
        triggered_by_message_id=_val(row, "triggered_by_message_id"),
        status=_val(row, "status", "PENDING"),
        sent_at=_val(row, "sent_at"),
        created_at=_val(row, "created_at"),
    )

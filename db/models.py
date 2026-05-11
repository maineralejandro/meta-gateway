from dataclasses import dataclass

import aiosqlite


@dataclass
class Agent:
    id: int | None = None
    name: str = ""
    description: str = ""
    system_prompt: str = ""
    escalation_marker: str = "ESCALATE_TO_HUMAN"
    fallback_responses: str = "{}"
    is_active: int = 1
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
    requires_human_review: int = 0
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
    llm_escalate: int = 0
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
    is_active: int = 1
    config_json: str = "{}"
    created_at: str | None = None
    updated_at: str | None = None


def row_to_agent(row: aiosqlite.Row | None) -> Agent | None:
    if row is None:
        return None
    return Agent(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        system_prompt=row["system_prompt"],
        escalation_marker=row["escalation_marker"],
        fallback_responses=row["fallback_responses"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def row_to_conversation(row: aiosqlite.Row | None) -> Conversation | None:
    if row is None:
        return None
    return Conversation(
        phone=row["phone"],
        contact_name=row["contact_name"],
        state=row["state"],
        last_message_at=row["last_message_at"],
        requires_human_review=row["requires_human_review"],
        unread_count=row["unread_count"],
        sentiment_score=row["sentiment_score"],
        confidence=row["confidence"],
        agent_id=row["agent_id"],
        current_session_id=row["current_session_id"],
        created_at=row["created_at"],
    )


def row_to_message(row: aiosqlite.Row | None) -> Message | None:
    if row is None:
        return None
    return Message(
        id=row["id"],
        phone=row["phone"],
        direction=row["direction"],
        source=row["source"],
        text=row["text"],
        media_type=row["media_type"],
        media_url=row["media_url"],
        meta_message_id=row["meta_message_id"],
        session_id=row["session_id"],
        correlation_id=row["correlation_id"] if "correlation_id" in row.keys() else None,  # noqa: SIM118        created_at=row["created_at"],
    )


def row_to_session(row: aiosqlite.Row | None) -> Session | None:
    if row is None:
        return None
    return Session(
        id=row["id"],
        phone=row["phone"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        end_reason=row["end_reason"],
        summary=row["summary"],
        message_count=row["message_count"],
    )


def row_to_agent_decision(row: aiosqlite.Row | None) -> AgentDecision | None:
    if row is None:
        return None
    return AgentDecision(
        id=row["id"],
        message_id=row["message_id"],
        phone=row["phone"],
        sentiment=row["sentiment"],
        sentiment_score=row["sentiment_score"],
        confidence=row["confidence"],
        llm_escalate=row["llm_escalate"],
        escalate_reason=row["escalate_reason"],
        history_count=row["history_count"],
        agent_name=row["agent_name"],
        correlation_id=row["correlation_id"] if "correlation_id" in row.keys() else None,  # noqa: SIM118        created_at=row["created_at"],
    )


def row_to_memory(row: aiosqlite.Row | None) -> ConversationMemory | None:
    if row is None:
        return None
    return ConversationMemory(
        phone=row["phone"],
        summary=row["summary"],
        key_facts=row["key_facts"],
        total_messages_summarized=row["total_messages_summarized"],
        updated_at=row["updated_at"],
    )


def row_to_agent_capability(row: aiosqlite.Row | None) -> AgentCapability | None:
    if row is None:
        return None
    return AgentCapability(
        id=row["id"],
        agent_id=row["agent_id"],
        capability_name=row["capability_name"],
        is_active=row["is_active"],
        config_json=row["config_json"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
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


def row_to_agent_template(row: aiosqlite.Row | None) -> AgentTemplate | None:
    if row is None:
        return None
    return AgentTemplate(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        system_prompt_template=row["system_prompt_template"],
        capabilities=row["capabilities"],
        fallback_responses=row["fallback_responses"],
        created_at=row["created_at"],
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


def row_to_turn(row: aiosqlite.Row | None) -> Turn | None:
    if row is None:
        return None
    return Turn(
        id=row["id"],
        phone=row["phone"],
        user_text=row["user_text"],
        assistant_text=row["assistant_text"],
        user_correlation_id=row["user_correlation_id"],
        assistant_correlation_id=row["assistant_correlation_id"],
        message_ids=row["message_ids"] if "message_ids" in row else "[]",  # noqa: SIM401
        session_id=row["session_id"] if "session_id" in row.keys() else None,  # noqa: SIM118
        created_at=row["created_at"],
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


def row_to_inference_trace(row: aiosqlite.Row | None) -> InferenceTrace | None:
    if row is None:
        return None
    return InferenceTrace(
        id=row["id"],
        phone=row["phone"],
        correlation_id=row["correlation_id"],
        agent_id=row["agent_id"],
        request_messages=row["request_messages"],
        response_raw=row["response_raw"],
        response_source=row["response_source"],
        error_type=row["error_type"],
        error_message=row["error_message"],
        token_usage_prompt=row["token_usage_prompt"],
        token_usage_completion=row["token_usage_completion"],
        latency_ms=row["latency_ms"],
        created_at=row["created_at"],
    )

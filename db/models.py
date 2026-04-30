from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Agent:
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    system_prompt: str = ""
    escalation_marker: str = "ESCALATE_TO_HUMAN"
    fallback_responses: str = "{}"
    is_active: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Session:
    id: str
    phone: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    end_reason: Optional[str] = None
    summary: Optional[str] = None
    message_count: int = 0


@dataclass
class Conversation:
    phone: str
    contact_name: Optional[str] = None
    state: str = "BOT_ACTIVE"
    last_message_at: Optional[str] = None
    requires_human_review: int = 0
    unread_count: int = 0
    sentiment_score: Optional[float] = None
    confidence: Optional[float] = None
    agent_id: Optional[int] = 1
    current_session_id: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class Message:
    id: int
    phone: str
    direction: str
    source: str
    text: Optional[str] = None
    media_type: Optional[str] = None
    media_url: Optional[str] = None
    meta_message_id: Optional[str] = None
    session_id: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class EscalationEvent:
    id: int = 0
    phone: str = ""
    from_state: str = ""
    to_state: str = ""
    reason: Optional[str] = None
    sentiment_score: Optional[float] = None
    confidence: Optional[float] = None
    created_at: Optional[str] = None


@dataclass
class AgentDecision:
    id: Optional[int] = None
    message_id: Optional[int] = None
    phone: str = ""
    sentiment: str = "neutral"
    sentiment_score: float = 0.5
    confidence: float = 0.5
    llm_escalate: int = 0
    escalate_reason: Optional[str] = None
    history_count: int = 0
    agent_name: str = ""
    created_at: Optional[str] = None


@dataclass
class ConversationMemory:
    phone: str
    summary: str = ""
    key_facts: str = "[]"
    total_messages_summarized: int = 0
    updated_at: Optional[str] = None


def row_to_agent(row) -> Optional[Agent]:
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


def row_to_conversation(row) -> Optional[Conversation]:
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


def row_to_message(row) -> Optional[Message]:
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
        created_at=row["created_at"],
    )


def row_to_session(row) -> Optional[Session]:
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


def row_to_agent_decision(row) -> Optional[AgentDecision]:
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
        created_at=row["created_at"],
    )


def row_to_memory(row) -> Optional[ConversationMemory]:
    if row is None:
        return None
    return ConversationMemory(
        phone=row["phone"],
        summary=row["summary"],
        key_facts=row["key_facts"],
        total_messages_summarized=row["total_messages_summarized"],
        updated_at=row["updated_at"],
    )

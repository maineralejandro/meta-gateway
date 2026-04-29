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
        created_at=row["created_at"],
    )

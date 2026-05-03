from dataclasses import asdict
from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from core.events import emit
from core.metrics import refresh_active_conversations, refresh_active_sessions
from db.database import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class UpdateStateRequest(BaseModel):
    phone: str
    state: str


class CloseSessionRequest(BaseModel):
    summary: str = ""


@router.get("")
async def get_conversations(limit: int = 100, offset: int = 0) -> Any:
    limit = min(limit, 500)
    db = await get_db()
    conversations = await db.get_all_conversations(limit=limit, offset=offset)
    return [asdict(c) for c in conversations]


@router.post("/state")
async def update_state(req: UpdateStateRequest) -> dict[str, Any]:
    db = await get_db()

    conv = await db.get_conversation(req.phone)
    old_state = conv.state if conv else "BOT_ACTIVE"

    ops: list[tuple[str, tuple[Any, ...]]] = []
    if not conv:
        ops = [
            ("INSERT INTO conversations (phone, state, last_message_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (req.phone, req.state)),
        ]
    else:
        ops = [
            ("UPDATE conversations SET state=?, requires_human_review=? WHERE phone=?",
            (req.state, 1 if req.state != "BOT_ACTIVE" else 0, req.phone)),
        ]

    if old_state != req.state:
        ops.append(
            ("INSERT INTO escalation_events (phone, from_state, to_state, reason) VALUES (?, ?, ?, ?)",
             (req.phone, old_state, req.state, "manual_change")),
        )

    await db.execute_transaction(ops)

    await refresh_active_conversations(db)

    await emit("state-changed", {
        "phone": req.phone,
        "state": req.state,
        "old_state": old_state,
    })

    logger.info("state_updated", phone=req.phone, old=old_state, new=req.state)
    return {"status": "ok", "old_state": old_state, "new_state": req.state}


class ChangeAgentRequest(BaseModel):
    phone: str
    agent_id: int


@router.post("/agent")
async def change_agent(req: ChangeAgentRequest) -> dict[str, Any]:
    db = await get_db()
    await db.execute(
        "UPDATE conversations SET agent_id=? WHERE phone=?", (req.agent_id, req.phone)
    )
    await db.commit()
    logger.info("agent_changed", phone=req.phone, agent_id=req.agent_id)
    return {"status": "ok", "agent_id": req.agent_id}


@router.get("/{phone}")
async def get_conversation(phone: str) -> Any:
    db = await get_db()
    conv = await db.get_conversation(phone)
    if not conv:
        return {"error": "not_found"}
    return asdict(conv)


@router.post("/{phone}/reset-unread")
async def reset_unread(phone: str) -> dict[str, str]:
    db = await get_db()
    await db.execute_transaction([
        ("UPDATE conversations SET unread_count=0 WHERE phone=?", (phone,)),
    ])
    return {"status": "ok"}


@router.post("/{phone}/close-session")
async def close_session(phone: str, req: CloseSessionRequest) -> dict[str, Any]:
    db = await get_db()
    conv = await db.get_conversation(phone)

    if not conv or not conv.current_session_id:
        return {"status": "error", "message": "No active session found"}

    session_id = conv.current_session_id
    await db.close_session(session_id, reason="manual", summary=req.summary)

    # Limpiar la referencia en la conversación
    await db.execute(
        "UPDATE conversations SET current_session_id=NULL, state='BOT_ACTIVE', requires_human_review=0 WHERE phone=?",
        (phone,),
    )
    await db.commit()

    await refresh_active_conversations(db)
    await refresh_active_sessions(db)

    logger.info("session_closed_manually", phone=phone, session_id=session_id)
    return {"status": "ok", "session_id": session_id}

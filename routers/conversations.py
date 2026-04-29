from fastapi import APIRouter
from db.database import get_db
from db.models import Conversation
from routers.ws import manager
from pydantic import BaseModel
from dataclasses import asdict
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class UpdateStateRequest(BaseModel):
    phone: str
    state: str


@router.get("")
async def get_conversations():
    db = await get_db()
    conversations = await db.get_all_conversations()
    return [asdict(c) for c in conversations]


@router.post("/state")
async def update_state(req: UpdateStateRequest):
    db = await get_db()

    conv = await db.get_conversation(req.phone)
    old_state = conv.state if conv else "BOT_ACTIVE"

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

    await manager.send_to_all({
        "type": "state-changed",
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
async def change_agent(req: ChangeAgentRequest):
    db = await get_db()
    await db.execute(
        "UPDATE conversations SET agent_id=? WHERE phone=?", (req.agent_id, req.phone)
    )
    await db.commit()
    logger.info("agent_changed", phone=req.phone, agent_id=req.agent_id)
    return {"status": "ok", "agent_id": req.agent_id}


@router.get("/{phone}")
async def get_conversation(phone: str):
    db = await get_db()
    conv = await db.get_conversation(phone)
    if not conv:
        return {"error": "not_found"}
    return asdict(conv)


@router.post("/{phone}/reset-unread")
async def reset_unread(phone: str):
    db = await get_db()
    await db.execute_transaction([
        ("UPDATE conversations SET unread_count=0 WHERE phone=?", (phone,)),
    ])
    return {"status": "ok"}

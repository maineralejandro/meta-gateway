from fastapi import APIRouter
from db.database import get_db
from core.meta_client import meta_client
from routers.ws import manager
from pydantic import BaseModel
from dataclasses import asdict
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/messages", tags=["messages"])


class SendMessageRequest(BaseModel):
    phone: str
    message: str


@router.get("/{phone}")
async def get_messages(phone: str, limit: int = 100):
    db = await get_db()
    messages = await db.get_messages(phone, limit)
    return [asdict(m) for m in messages]


@router.post("/send")
async def send_message(req: SendMessageRequest):
    result = await meta_client.send_text(req.phone, req.message)

    db = await get_db()
    conv = await db.get_conversation(req.phone)
    session_id = conv.current_session_id if conv else None

    await db.execute_transaction([
        ("INSERT INTO messages (phone, direction, source, text, session_id) VALUES (?, 'outbound', 'human', ?, ?)",
         (req.phone, req.message, session_id)),
        ("UPDATE conversations SET last_message_at=CURRENT_TIMESTAMP WHERE phone=?",
         (req.phone,)),
    ])

    if session_id:
        await db.increment_session_message_count(session_id)

    await manager.send_to_all({
        "type": "human-sent",
        "phone": req.phone,
        "message": req.message,
        "direction": "outbound",
        "source": "human",
    })

    meta_ok = not result.get("error", False)
    status = "ok" if meta_ok else "meta_error"
    logger.info("human_message_sent", phone=req.phone, meta_ok=meta_ok)
    return {"status": status, "meta_response": result}


@router.get("/{phone}/decisions")
async def get_decisions(phone: str, limit: int = 50):
    db = await get_db()
    decisions = await db.get_decisions(phone, limit)
    return [asdict(d) for d in decisions]


@router.get("/{phone}/decisions/{message_id}")
async def get_decision_for_message(phone: str, message_id: int):
    db = await get_db()
    decision = await db.get_decision_for_message(message_id)
    if decision is None:
        return {"error": "not_found"}
    return asdict(decision)

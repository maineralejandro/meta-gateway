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
    await db.execute_transaction([
        ("INSERT INTO messages (phone, direction, source, text) VALUES (?, 'outbound', 'human', ?)",
         (req.phone, req.message)),
        ("UPDATE conversations SET last_message_at=CURRENT_TIMESTAMP WHERE phone=?",
         (req.phone,)),
    ])

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

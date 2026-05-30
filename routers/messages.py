from dataclasses import asdict
from typing import Any

import structlog
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from core.events import emit
from core.meta_client import meta_client
from core.metrics import MESSAGES_SENT
from db.database import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/api/messages", tags=["messages"])


class SendMessageRequest(BaseModel):
    phone: str
    message: str


@router.get("/{phone}")
async def get_messages(phone: str, limit: int = 100) -> Any:
    db = await get_db()
    messages = await db.get_messages(phone, limit)
    return [asdict(m) for m in messages]


@router.post("/send")
async def send_message(req: SendMessageRequest) -> dict[str, Any]:
    db = await get_db()
    conv = await db.get_conversation(req.phone)
    session_id = conv.current_session_id if conv else None

    await db.insert_message(req.phone, "outbound", "human", req.message, session_id=session_id)
    await db.execute_transaction([
        ("UPDATE conversations SET last_message_at=NOW() WHERE phone=$1", (req.phone,)),
    ])

    if session_id:
        await db.increment_session_message_count(session_id)

    result = await meta_client.send_text(req.phone, req.message)

    await emit("human-sent", {
        "phone": req.phone,
        "message": req.message,
        "direction": "outbound",
        "source": "human",
    })
    MESSAGES_SENT.labels(source="human").inc()

    meta_ok = not result.get("error", False)
    status = "ok" if meta_ok else "meta_error"
    logger.info("human_message_sent", phone=req.phone, meta_ok=meta_ok)
    return {"status": status, "meta_response": result}


@router.get("/{phone}/decisions")
async def get_decisions(phone: str, limit: int = 50) -> Any:
    db = await get_db()
    decisions = await db.get_decisions(phone, limit)
    return [asdict(d) for d in decisions]


@router.get("/{phone}/decisions/{message_id}")
async def get_decision_for_message(phone: str, message_id: int) -> Any:
    db = await get_db()
    decision = await db.get_decision_for_message(message_id)
    if decision is None:
        return {"error": "not_found"}
    return asdict(decision)


@router.get("/media-proxy/{media_id}")
async def media_proxy(media_id: str) -> Any:
    media_url = await meta_client.retrieve_media_url(media_id)
    if not media_url:
        return Response(content=b'{"error":"media_not_found"}', status_code=404, media_type="application/json")
    result = await meta_client.download_media(media_url)
    if not result:
        return Response(content=b'{"error":"download_failed"}', status_code=502, media_type="application/json")
    content, content_type = result
    return Response(content=content, media_type=content_type)

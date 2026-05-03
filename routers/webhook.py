import asyncio
import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from structlog.contextvars import bind_contextvars, clear_contextvars

from core.config import settings
from core.events import emit
from core.hitl_router import hitl_router
from core.meta_client import meta_client
from core.metrics import RATE_LIMITS, WEBHOOK_DUPLICATES
from core.security import rate_limiter, verify_meta_signature
from core.sessions import session_manager
from core.task_tracker import track_task
from db.database import get_db

logger = structlog.get_logger()
router = APIRouter()


async def _safe_process(phone: str, text: str) -> None:
    try:
        await hitl_router.process_inbound_message(phone, text)
    except Exception as e:
        logger.error("safe_process_error", phone=phone, error=str(e))
        try:
            await emit("error", {"phone": phone, "error": str(e)})
            await meta_client.send_text(
                phone,
                "Disculpa, ocurrió un error. Por favor intenta de nuevo.",
            )
        except Exception:
            logger.error("safe_process_fallback_failed", phone=phone)


@router.get("/webhook/whatsapp")
async def verify_webhook(request: Request) -> PlainTextResponse:
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("webhook_verified")
        return PlainTextResponse(content=challenge or "")
    raise HTTPException(status_code=403, detail="Invalid verify token")


@router.post("/webhook/whatsapp")
async def receive_webhook(request: Request) -> Any:
    correlation_id = uuid.uuid4().hex[:12]
    bind_contextvars(correlation_id=correlation_id)
    try:
        return await _receive_webhook_inner(request)
    finally:
        clear_contextvars()


async def _receive_webhook_inner(request: Request) -> Any:
    body = await request.body()
    if not await verify_meta_signature(request, body):
        return Response(status_code=403)

    try:
        data = json.loads(body)
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

            if "messages" in value:
                msg = value["messages"][0]
                phone = msg["from"]

                if not rate_limiter.is_allowed(phone):
                    RATE_LIMITS.inc()
                    logger.warning("rate_limit_exceeded", phone=phone)
                    return {"status": "rate_limited"}

                msg_type = msg.get("type", "text")
                meta_msg_id = msg.get("id", "")

                text = ""
                media_type = None
                media_url = None

                if msg_type == "text":
                    text = msg.get("text", {}).get("body", "")
                else:
                    text = f"[{msg_type}]"
                    media_type = msg_type
                    if msg_type == "image":
                        media_url = msg.get("image", {}).get("id", "")
                    elif msg_type == "document":
                        media_url = msg.get("document", {}).get("id", "")
                    elif msg_type == "audio":
                        media_url = msg.get("audio", {}).get("id", "")
                    elif msg_type == "location":
                        loc = msg.get("location", {})
                        text = f"[location] {loc.get('name', '')} {loc.get('latitude')},{loc.get('longitude')}"

                db = await get_db()

                row = await db.fetchone(
                    "SELECT state, requires_human_review FROM conversations WHERE phone=?",
                    (phone,),
                )

                if not row:
                    await db.execute_transaction([
                        ("INSERT INTO conversations (phone, state, last_message_at) VALUES (?, 'BOT_ACTIVE', CURRENT_TIMESTAMP)", (phone,)),
                    ])
                    state = "BOT_ACTIVE"
                    requires_human = False
                else:
                    state, requires_human = row

                session_id = await session_manager.get_or_create_session(phone)

                try:
                    await db.insert_message(
                        phone, "inbound", "customer", text,
                        media_type=media_type, media_url=media_url,
                        meta_message_id=meta_msg_id, session_id=session_id,
                    )
                    await db.execute_transaction([
                        ("UPDATE conversations SET last_message_at=CURRENT_TIMESTAMP, unread_count=unread_count+1 WHERE phone=?", (phone,)),
                    ])
                except Exception as e:
                    if "UNIQUE constraint" in str(e) and "meta_message_id" in str(e):
                        WEBHOOK_DUPLICATES.inc()
                        logger.info("duplicate_webhook_ignored", meta_msg_id=meta_msg_id, phone=phone)
                        return {"status": "duplicate"}
                    raise

                await db.increment_session_message_count(session_id)

                await emit("new-message", {
                    "phone": phone,
                    "message": text,
                    "direction": "inbound",
                    "source": "customer",
                    "state": state,
                })

                if state == "HUMAN_ONLY" or requires_human:
                    await emit("waiting-for-human", {"phone": phone})
                    return {"status": "pending_human"}
                if state == "PENDING_APPROVAL":
                    return {"status": "pending_approval"}
                track_task(asyncio.create_task(_safe_process(phone, text)))
                return {"status": "processing"}

            if "statuses" in value:
                status = value["statuses"][0]
                logger.info("message_status", status=status.get("status"), id=status.get("id"))
                return {"status": "ok"}

    except Exception as e:
        logger.error("webhook_error", error=str(e))
        return {"status": "error"}

    return {"status": "ok"}

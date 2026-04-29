from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse
from db.database import get_db
from core.config import settings
from routers.ws import manager

import asyncio
import structlog

logger = structlog.get_logger()
router = APIRouter()

from core.hitl_router import process_inbound_message


@router.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("webhook_verified")
        return PlainTextResponse(content=challenge or "")
    raise HTTPException(status_code=403, detail="Invalid verify token")


@router.post("/webhook/whatsapp")
async def receive_webhook(request: Request):
    data = await request.json()

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                if "messages" in value:
                    msg = value["messages"][0]
                    phone = msg["from"]
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
                            ("INSERT INTO conversations (phone, state, last_message_at) VALUES (?, 'BOT_ACTIVE', CURRENT_TIMESTAMP)",
                             (phone,)),
                        ])
                        state = "BOT_ACTIVE"
                        requires_human = False
                    else:
                        state, requires_human = row

                    await db.execute_transaction([
                        ("INSERT INTO messages (phone, direction, source, text, media_type, media_url, meta_message_id) VALUES (?, 'inbound', 'customer', ?, ?, ?, ?)",
                         (phone, text, media_type, media_url, meta_msg_id)),
                        ("UPDATE conversations SET last_message_at=CURRENT_TIMESTAMP, unread_count=unread_count+1 WHERE phone=?",
                         (phone,)),
                    ])

                    await manager.send_to_all({
                        "type": "new-message",
                        "phone": phone,
                        "message": text,
                        "direction": "inbound",
                        "source": "customer",
                        "state": state,
                    })

                    if state == "HUMAN_ONLY" or requires_human:
                        await manager.send_to_all({
                            "type": "waiting-for-human",
                            "phone": phone,
                        })
                        return {"status": "pending_human"}
                    elif state == "PENDING_APPROVAL":
                        return {"status": "pending_approval"}
                    else:
                        asyncio.create_task(process_inbound_message(phone, text))
                        return {"status": "processing"}

                elif "statuses" in value:
                    status = value["statuses"][0]
                    logger.info("message_status", status=status.get("status"), id=status.get("id"))
                    return {"status": "ok"}

    except Exception as e:
        logger.error("webhook_error", error=str(e))
        return {"status": "error", "detail": str(e)}

    return {"status": "ok"}

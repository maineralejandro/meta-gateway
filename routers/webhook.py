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
from core.meta_client import meta_client
from core.metrics import RATE_LIMITS, WEBHOOK_DUPLICATES
from core.security import rate_limiter, verify_meta_signature
from core.sessions import session_manager
from core.turn_builder import turn_builder
from db.database import get_db

logger = structlog.get_logger()
router = APIRouter()


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
        return await _receive_webhook_inner(request, correlation_id=correlation_id)
    finally:
        clear_contextvars()


async def _handle_message(msg: dict[str, Any], value: dict[str, Any], correlation_id: str) -> dict[str, Any]:
    phone = msg["from"]

    if not rate_limiter.is_allowed(phone):
        RATE_LIMITS.inc()
        logger.warning("rate_limit_exceeded", phone=phone)
        return {"status": "rate_limited"}

    msg_type = msg.get("type", "text")
    meta_msg_id = msg.get("id", "")

    if settings.MARK_READ_DELAY_MS > 0:
        await asyncio.sleep(settings.MARK_READ_DELAY_MS / 1000.0)

    try:
        await meta_client.mark_read(meta_msg_id)
    except Exception:
        logger.debug("mark_read_failed", meta_msg_id=meta_msg_id)

    try:
        await meta_client.mark_read_with_typing(meta_msg_id)
    except Exception:
        logger.debug("mark_read_typing_failed", meta_msg_id=meta_msg_id)

    text = ""
    media_type = None
    media_url = None
    product_list_reply_key: str | None = None

    if msg_type == "text":
        text = msg.get("text", {}).get("body", "")
    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        interactive_type = interactive.get("type", "")
        if interactive_type == "button_reply":
            reply = interactive.get("button_reply", {})
            text = reply.get("title", reply.get("id", ""))
            media_type = "interactive_button"
            media_url = reply.get("id")
            if media_url and media_url.startswith("add_to_cart_"):
                item_key = media_url[len("add_to_cart_"):]
                try:
                    from core.cart_state import cart_state
                    await cart_state.add_item(phone, item_key, 1)
                    item_name = cart_state._catalog.get(item_key, {}).get("name", item_key)
                    text = f"Quiero agregar {item_name} al carrito"
                except Exception as e:
                    logger.warning("add_to_cart_button_failed", phone=phone, item_key=item_key, error=str(e))
            elif media_url and media_url.startswith("view_details_"):
                item_key = media_url[len("view_details_"):]
                text = f"Quiero ver detalles de {item_key}"
        elif interactive_type == "list_reply":
            reply = interactive.get("list_reply", {})
            text = reply.get("title", reply.get("id", ""))
            media_type = "interactive_list"
            media_url = reply.get("id")
            if media_url and media_url.startswith("category_"):
                text = f"Quiero ver la categoria {text}"
            elif media_url and not media_url.startswith("category_"):
                product_list_reply_key = media_url
        else:
            text = f"[interactive:{interactive_type}]"
            media_type = "interactive"
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

    if product_list_reply_key:
        try:
            from core.cart_state import cart_state
            catalog = cart_state.get_catalog()
            if product_list_reply_key in catalog:
                item_name = catalog[product_list_reply_key].get("name", text)
                price = catalog[product_list_reply_key].get("price", 0)
                await meta_client.send_interactive_buttons(
                    phone,
                    f"{item_name} - ${price:,}",
                    [
                        {"id": f"add_to_cart_{product_list_reply_key}", "title": "Agregar al carrito"},
                        {"id": f"view_details_{product_list_reply_key}", "title": "Ver detalles"},
                    ],
                )
                session_id = await session_manager.get_or_create_session(phone)
                await db.insert_message_and_touch_conversation(
                    phone, "outbound", "bot", f"[interactive buttons: add_to_cart / view_details for {product_list_reply_key}]",
                    media_type="interactive_button", session_id=session_id, correlation_id=correlation_id,
                )
                return {"status": "action_buttons_sent"}
        except Exception as e:
            logger.warning("product_list_reply_buttons_failed", phone=phone, error=str(e))

    row = await db.fetchone(
        "SELECT state, requires_human_review FROM conversations WHERE phone=$1",
        phone,
    )

    if not row:
        await db.create_conversation(phone)
        state = "BOT_ACTIVE"
        requires_human = False
    else:
        state = row["state"]
        requires_human = row["requires_human_review"]

    session_id = await session_manager.get_or_create_session(phone)

    try:
        message_id = await db.insert_message_and_touch_conversation(
            phone, "inbound", "customer", text,
            media_type=media_type, media_url=media_url,
            meta_message_id=meta_msg_id, session_id=session_id,
            correlation_id=correlation_id,
        )
    except Exception as e:
        if ("unique" in str(e).lower() or "UNIQUE constraint" in str(e)) and "meta_message_id" in str(e):
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
        if media_type == "interactive_button" and media_url == "continue_with_bot":
            await db.update_conversation_state(phone, "BOT_ACTIVE", requires_human_review=False)
            await emit("state-changed", {"phone": phone, "state": "BOT_ACTIVE"})
            state = "BOT_ACTIVE"
        else:
            await emit("waiting-for-human", {"phone": phone})
            return {"status": "pending_human"}
    if state == "PENDING_APPROVAL":
        if media_type == "interactive_button" and media_url == "continue_with_bot":
            await db.update_conversation_state(phone, "BOT_ACTIVE", requires_human_review=False)
            await emit("state-changed", {"phone": phone, "state": "BOT_ACTIVE"})
            state = "BOT_ACTIVE"
        else:
            return {"status": "pending_approval"}
    await turn_builder.debounce(phone, text, correlation_id=correlation_id, message_id=message_id, session_id=session_id)
    return {"status": "processing"}


async def _receive_webhook_inner(request: Request, correlation_id: str = "") -> Any:
    body = await request.body()
    if not await verify_meta_signature(request, body):
        return Response(status_code=403)

    try:
        data = json.loads(body)
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                if "messages" in value:
                    return await _handle_message(value["messages"][0], value, correlation_id)

                if "statuses" in value:
                    status_entry = value["statuses"][0]
                    status_val = status_entry.get("status")
                    msg_id = status_entry.get("id")
                    recipient_phone = status_entry.get("recipient_id")
                    logger.info("message_status", status=status_val, id=msg_id)
                try:
                    db = await get_db()
                    await db.execute(
                        "UPDATE messages SET meta_status=$1, meta_status_at=NOW() WHERE meta_message_id=$2",
                        status_val, msg_id,
                    )
                except Exception as e:
                    logger.warning("status_persist_failed", msg_id=msg_id, error=str(e))
                if status_val == "delivered" and recipient_phone:
                    try:
                        from datetime import UTC, datetime, timedelta

                        from core.scheduler import message_scheduler
                        scheduled_at = (datetime.now(tz=UTC) + timedelta(minutes=settings.FOLLOW_UP_DELAY_MINUTES)).isoformat()
                        await message_scheduler.schedule(
                            phone=recipient_phone,
                            template_name="follow_up",
                            scheduled_at=scheduled_at,
                            triggered_by_message_id=msg_id,
                        )
                    except Exception as e:
                        logger.warning("follow_up_schedule_failed", phone=recipient_phone, error=str(e))
                    if recipient_phone:
                        await emit("message-status", {
                            "phone": recipient_phone,
                            "message_id": msg_id,
                            "status": status_val,
                        })
                    return {"status": "ok"}

    except Exception as e:
        logger.error("webhook_error", error=str(e))
        return {"status": "error"}

    return {"status": "ok"}

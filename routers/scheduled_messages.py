import json
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.scheduler import message_scheduler
from db.database import get_db
from db.models import ScheduledMessage

logger = structlog.get_logger()
router = APIRouter(prefix="/api/scheduled-messages", tags=["scheduled-messages"])


class CreateScheduledMessageRequest(BaseModel):
    phone: str
    template_name: str
    components: list[dict[str, Any]] | None = None
    scheduled_at: str


class ScheduledMessageResponse(BaseModel):
    id: int
    phone: str
    template_name: str
    components_json: str = "[]"
    scheduled_at: str | None = None
    triggered_by_message_id: str | None = None
    status: str = "PENDING"
    sent_at: str | None = None
    created_at: str | None = None


def _to_response(sm: ScheduledMessage) -> dict[str, Any]:
    return {
        "id": sm.id,
        "phone": sm.phone,
        "template_name": sm.template_name,
        "components_json": sm.components_json,
        "scheduled_at": sm.scheduled_at,
        "triggered_by_message_id": sm.triggered_by_message_id,
        "status": sm.status,
        "sent_at": sm.sent_at,
        "created_at": sm.created_at,
    }


@router.get("", response_model=list[ScheduledMessageResponse])
async def list_scheduled_messages(
    phone: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    db = await get_db()
    messages = await db.scheduled_messages.get_all(phone=phone, status=status, limit=limit, offset=offset)
    return [_to_response(m) for m in messages]


@router.post("", response_model=ScheduledMessageResponse, status_code=201)
async def create_scheduled_message(req: CreateScheduledMessageRequest) -> Any:
    components_json = json.dumps(req.components or [])
    msg_id = await message_scheduler.schedule(
        phone=req.phone,
        template_name=req.template_name,
        scheduled_at=req.scheduled_at,
        components_json=components_json,
    )
    db = await get_db()
    sm = await db.scheduled_messages.get(msg_id)
    if not sm:
        raise HTTPException(status_code=500, detail="Failed to retrieve scheduled message")
    return _to_response(sm)


@router.delete("/{msg_id}", status_code=204)
async def cancel_scheduled_message(msg_id: int) -> None:
    db = await get_db()
    sm = await db.scheduled_messages.get(msg_id)
    if not sm:
        raise HTTPException(status_code=404, detail="Scheduled message not found")
    if sm.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Cannot cancel message in status '{sm.status}'")
    await db.scheduled_messages.cancel(msg_id)


@router.post("/re-engage", response_model=dict)
async def trigger_re_engagement() -> Any:
    count = await message_scheduler.run_re_engagement()
    return {"scheduled": count}

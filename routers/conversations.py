from dataclasses import asdict
from typing import Any

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
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
    result = await db.update_state_atomic(req.phone, req.state)

    await refresh_active_conversations(db)

    await emit("state-changed", {
        "phone": req.phone,
        "state": req.state,
        "old_state": result["old_state"],
    })

    logger.info("state_updated", phone=req.phone, old=result["old_state"], new=req.state)
    return {"status": "ok", "old_state": result["old_state"], "new_state": req.state}


class ChangeAgentRequest(BaseModel):
    phone: str
    agent_id: int


@router.post("/agent")
async def change_agent(req: ChangeAgentRequest) -> dict[str, Any]:
    db = await get_db()
    await db.set_conversation_agent(req.phone, req.agent_id)
    logger.info("agent_changed", phone=req.phone, agent_id=req.agent_id)
    return {"status": "ok", "agent_id": req.agent_id}


@router.get("/{phone}")
async def get_conversation(phone: str) -> Any:
    db = await get_db()
    conv = await db.get_conversation(phone)
    if not conv:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return asdict(conv)


@router.post("/{phone}/reset-unread")
async def reset_unread(phone: str) -> dict[str, str]:
    db = await get_db()
    await db.execute_transaction([
        ("UPDATE conversations SET unread_count=0 WHERE phone=$1", (phone,)),
    ])
    return {"status": "ok"}


@router.post("/{phone}/close-session")
async def close_session(phone: str, req: CloseSessionRequest) -> dict[str, Any]:
    db = await get_db()
    session_id = await db.close_session_and_reset(phone, reason="manual", summary=req.summary)

    if not session_id:
        return {"status": "error", "message": "No active session found"}

    await refresh_active_conversations(db)
    await refresh_active_sessions(db)

    logger.info("session_closed_manually", phone=phone, session_id=session_id)
    return {"status": "ok", "session_id": session_id}


class AddNoteRequest(BaseModel):
    note: str
    author: str = "human"


@router.get("/{phone}/notes")
async def get_notes(phone: str) -> Any:
    db = await get_db()
    return await db.get_conversation_notes(phone)


@router.post("/{phone}/notes")
async def add_note(phone: str, req: AddNoteRequest) -> Any:
    db = await get_db()
    return await db.add_conversation_note(phone, req.note, req.author)


@router.delete("/{phone}/notes/{note_id}")
async def delete_note(phone: str, note_id: int) -> Any:
    db = await get_db()
    deleted = await db.delete_conversation_note(note_id, phone)
    if not deleted:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return {"status": "ok"}

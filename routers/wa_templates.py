import json
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import settings
from core.meta_client import meta_client
from db.database import get_db
from db.models import WhatsAppTemplate

logger = structlog.get_logger()
router = APIRouter(prefix="/api/wa-templates", tags=["wa-templates"])


class CreateWATemplateRequest(BaseModel):
    template_name: str
    template_type: str = "UTILITY"
    category: str = "UTILITY"
    language: str = "es"
    body_text: str
    header_text: str | None = None
    header_image_url: str | None = None
    footer_text: str | None = None
    buttons: list[dict[str, Any]] | None = None


class UpdateWATemplateRequest(BaseModel):
    body_text: str | None = None
    header_text: str | None = None
    header_image_url: str | None = None
    footer_text: str | None = None
    buttons: list[dict[str, Any]] | None = None


class WATemplateResponse(BaseModel):
    id: int
    template_name: str
    template_type: str
    category: str
    language: str
    status: str
    body_text: str
    header_text: str | None = None
    header_image_url: str | None = None
    footer_text: str | None = None
    buttons_json: str = "[]"
    meta_template_id: str | None = None
    meta_quality_rating: str | None = None
    rejection_reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


def _to_response(t: WhatsAppTemplate) -> dict[str, Any]:
    return {
        "id": t.id,
        "template_name": t.template_name,
        "template_type": t.template_type,
        "category": t.category,
        "language": t.language,
        "status": t.status,
        "body_text": t.body_text,
        "header_text": t.header_text,
        "header_image_url": t.header_image_url,
        "footer_text": t.footer_text,
        "buttons_json": t.buttons_json,
        "meta_template_id": t.meta_template_id,
        "meta_quality_rating": t.meta_quality_rating,
        "rejection_reason": t.rejection_reason,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def _build_meta_components(req: CreateWATemplateRequest) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    if req.header_text:
        components.append({"type": "HEADER", "format": "TEXT", "text": req.header_text})
    elif req.header_image_url:
        components.append({
            "type": "HEADER",
            "format": "IMAGE",
            "example": {"header_handle": [req.header_image_url]},
        })
    components.append({"type": "BODY", "text": req.body_text})
    if req.footer_text:
        components.append({"type": "FOOTER", "text": req.footer_text})
    if req.buttons:
        for btn in req.buttons:
            sub_type = btn.get("sub_type", "QUICK_REPLY")
            components.append({
                "type": "BUTTON",
                "sub_type": sub_type,
                "text": btn.get("text", ""),
                **({"example": btn.get("example")} if btn.get("example") else {}),
            })
    return components


@router.get("", response_model=list[WATemplateResponse])
async def list_wa_templates(
    agent_id: int | None = None,
    status: str | None = None,
) -> Any:
    db = await get_db()
    templates = await db.whatsapp_templates.get_all(agent_id=agent_id, status=status)
    return [_to_response(t) for t in templates]


@router.get("/{template_id}", response_model=WATemplateResponse)
async def get_wa_template(template_id: int) -> Any:
    db = await get_db()
    t = await db.whatsapp_templates.get(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return _to_response(t)


@router.post("", response_model=WATemplateResponse, status_code=201)
async def create_wa_template(req: CreateWATemplateRequest) -> Any:
    db = await get_db()
    existing = await db.whatsapp_templates.get_by_name(req.template_name)
    if existing:
        raise HTTPException(status_code=409, detail="Template name already exists")

    buttons_json = json.dumps(req.buttons or [])
    t = WhatsAppTemplate(
        template_name=req.template_name,
        template_type=req.template_type,
        category=req.category,
        language=req.language,
        body_text=req.body_text,
        header_text=req.header_text,
        header_image_url=req.header_image_url,
        footer_text=req.footer_text,
        buttons_json=buttons_json,
    )

    waba_id = settings.WHATSAPP_BUSINESS_ACCOUNT_ID
    if waba_id:
        try:
            components = _build_meta_components(req)
            meta_result = await meta_client.create_template(waba_id, {
                "name": req.template_name,
                "category": req.category,
                "language": req.language,
                "components": components,
            })
            meta_id = meta_result.get("id")
            if meta_id:
                t.meta_template_id = str(meta_id)
                t.status = "PENDING"
        except Exception as e:
            logger.warning("meta_template_create_failed", name=req.template_name, error=str(e))

    template_id = await db.whatsapp_templates.create(t)
    t.id = template_id
    return _to_response(t)


@router.put("/{template_id}", response_model=WATemplateResponse)
async def update_wa_template(template_id: int, req: UpdateWATemplateRequest) -> Any:
    db = await get_db()
    existing = await db.whatsapp_templates.get(template_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")

    updates: dict[str, Any] = {}
    if req.body_text is not None:
        updates["body_text"] = req.body_text
    if req.header_text is not None:
        updates["header_text"] = req.header_text
    if req.header_image_url is not None:
        updates["header_image_url"] = req.header_image_url
    if req.footer_text is not None:
        updates["footer_text"] = req.footer_text
    if req.buttons is not None:
        updates["buttons_json"] = json.dumps(req.buttons)

    await db.whatsapp_templates.update(template_id, **updates)
    t = await db.whatsapp_templates.get(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found after update")
    return _to_response(t)


@router.delete("/{template_id}", status_code=204)
async def delete_wa_template(template_id: int) -> None:
    db = await get_db()
    existing = await db.whatsapp_templates.get(template_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")

    waba_id = settings.WHATSAPP_BUSINESS_ACCOUNT_ID
    if waba_id and existing.template_name:
        try:
            await meta_client.delete_template(waba_id, existing.template_name)
        except Exception as e:
            logger.warning("meta_template_delete_failed", name=existing.template_name, error=str(e))

    await db.whatsapp_templates.delete(template_id)


@router.post("/sync", response_model=dict)
async def sync_wa_templates() -> Any:
    waba_id = settings.WHATSAPP_BUSINESS_ACCOUNT_ID
    if not waba_id:
        raise HTTPException(status_code=400, detail="WHATSAPP_BUSINESS_ACCOUNT_ID not configured")

    try:
        meta_templates = await meta_client.get_templates(waba_id)
    except Exception as e:
        logger.error("meta_template_sync_failed", error=str(e))
        raise HTTPException(status_code=502, detail=f"Meta API error: {e}") from None

    db = await get_db()
    synced = 0
    for mt in meta_templates:
        try:
            await db.whatsapp_templates.upsert_from_meta(mt)
            synced += 1
        except Exception as e:
            logger.warning("template_sync_item_failed", name=mt.get("name"), error=str(e))

    return {"synced": synced, "total": len(meta_templates)}

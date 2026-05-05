import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.capabilities.base import registry
from db.database import Database, get_db
from db.models import Agent, AgentCapability

router = APIRouter(prefix="/api/templates", tags=["templates"])


class TemplateResponse(BaseModel):
    id: int
    name: str
    description: str
    system_prompt_template: str
    capabilities: str
    fallback_responses: str
    created_at: str | None = None


class CreateFromTemplateRequest(BaseModel):
    template_id: int
    fields: dict[str, str] = {}


class AgentFromTemplateResponse(BaseModel):
    agent_id: int
    name: str
    capabilities_created: int


VARIABLE_RE = re.compile(r"\{\{(\w+)\}\}")


@router.get("", response_model=list[TemplateResponse])
async def list_templates(db: Database = Depends(get_db)) -> Any:
    return await db.get_all_templates()


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: int, db: Database = Depends(get_db)) -> Any:
    template = await db.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.post("/from-template", response_model=AgentFromTemplateResponse)
async def create_from_template(
    req: CreateFromTemplateRequest, db: Database = Depends(get_db)
) -> Any:
    template = await db.get_template(req.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    business_name = req.fields.get("business_name", "Mi Negocio")
    system_prompt = VARIABLE_RE.sub(
        lambda m: req.fields.get(m.group(1), m.group(0)),
        template.system_prompt_template,
    )

    agent_name = req.fields.get("name", business_name)
    agent = Agent(
        name=agent_name,
        description=template.description,
        system_prompt=system_prompt,
        fallback_responses=template.fallback_responses,
        is_active=1,
    )
    agent_id = await db.upsert_agent(agent)

    try:
        cap_list = json.loads(template.capabilities)
    except (json.JSONDecodeError, TypeError):
        cap_list = []

    available = set(registry.list_available())
    caps_created = 0
    for cap_def in cap_list:
        cap_name = cap_def.get("name", "")
        if cap_name not in available:
            continue
        cap_config = cap_def.get("config", {})
        ac = AgentCapability(
            agent_id=agent_id,
            capability_name=cap_name,
            is_active=1,
            config_json=json.dumps(cap_config),
        )
        await db.upsert_agent_capability(ac)
        caps_created += 1

    registry.invalidate(agent_id)

    return AgentFromTemplateResponse(
        agent_id=agent_id,
        name=agent_name,
        capabilities_created=caps_created,
    )

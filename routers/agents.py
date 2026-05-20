
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.capabilities.base import registry
from core.inference import inference_engine
from db.database import Database, get_db
from db.models import Agent, AgentCapability

router = APIRouter(prefix="/api/agents", tags=["agents"])

class AgentBase(BaseModel):
    name: str
    description: str = ""
    system_prompt: str
    escalation_marker: str = "ESCALATE_TO_HUMAN"
    fallback_responses: str = "{}"
    is_active: bool = True

class AgentCreate(AgentBase):
    pass

class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    escalation_marker: str | None = None
    fallback_responses: str | None = None
    is_active: bool | None = None

class AgentResponse(AgentBase):
    id: int

@router.get("", response_model=list[AgentResponse])
async def list_agents(db: Database = Depends(get_db)) -> Any:
    agents = await db.get_all_agents()
    return agents

@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: int, db: Database = Depends(get_db)) -> Any:
    agent = await db.get_agent(agent_id=agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent

@router.post("", response_model=AgentResponse)
async def create_agent(agent_in: AgentCreate, db: Database = Depends(get_db)) -> Any:
    agent = Agent(**agent_in.model_dump())
    agent_id = await db.upsert_agent(agent)
    agent.id = agent_id
    return agent

@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(agent_id: int, agent_in: AgentUpdate, db: Database = Depends(get_db)) -> Any:
    existing = await db.get_agent(agent_id=agent_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Agent not found")

    update_data = agent_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(existing, field, value)

    await db.upsert_agent(existing)
    return existing

@router.post("/{agent_id}/activate")
async def activate_agent(agent_id: int, db: Database = Depends(get_db)) -> dict[str, str]:
    existing = await db.get_agent(agent_id=agent_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Agent not found")

    await db.activate_agent(agent_id)
    await inference_engine.reload()
    return {"status": "success", "message": f"Agent {agent_id} activated"}

@router.post("/{agent_id}/reload")
async def reload_agent(agent_id: int) -> dict[str, Any]:
    from core.cart_state import cart_state
    await cart_state.reload_catalog_from_db()
    registry.invalidate(agent_id)
    await inference_engine.reload()
    return {
        "status": "success",
        "message": "Reloaded: catalog from DB + capability cache + inference cache",
        "catalog_items": len(cart_state._catalog),
        "needs_search": cart_state.needs_search,
    }


class CapabilityUpsertItem(BaseModel):
    capability_name: str
    is_active: bool = True
    config_json: str = "{}"


class CapabilityUpsertRequest(BaseModel):
    capabilities: list[CapabilityUpsertItem]


class AgentCapabilityResponse(BaseModel):
    id: int | None
    agent_id: int
    capability_name: str
    is_active: bool
    config_json: str
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


@router.get("/{agent_id}/capabilities", response_model=list[AgentCapabilityResponse])
async def get_agent_capabilities(agent_id: int, db: Database = Depends(get_db)) -> Any:
    agent = await db.get_agent(agent_id=agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await db.get_agent_capabilities(agent_id)


@router.put("/{agent_id}/capabilities", response_model=list[AgentCapabilityResponse])
async def upsert_agent_capabilities(
    agent_id: int, req: CapabilityUpsertRequest, db: Database = Depends(get_db)
) -> Any:
    agent = await db.get_agent(agent_id=agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    available = set(registry.list_available())
    for item in req.capabilities:
        if item.capability_name not in available:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown capability: {item.capability_name}",
            )

    for item in req.capabilities:
        ac = AgentCapability(
            agent_id=agent_id,
            capability_name=item.capability_name,
            is_active=item.is_active,
            config_json=item.config_json,
        )
        await db.upsert_agent_capability(ac)

    registry.invalidate(agent_id)
    return await db.get_agent_capabilities(agent_id)


@router.delete("/{agent_id}/capabilities/{capability_name}")
async def delete_agent_capability(
    agent_id: int, capability_name: str, db: Database = Depends(get_db)
) -> dict[str, str]:
    agent = await db.get_agent(agent_id=agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    existing = await db.get_agent_capabilities(agent_id)
    if not any(c.capability_name == capability_name for c in existing):
        raise HTTPException(status_code=404, detail="Capability not assigned to agent")

    await db.delete_agent_capability(agent_id, capability_name)
    registry.invalidate(agent_id)
    return {"status": "ok"}

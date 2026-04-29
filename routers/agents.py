from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from db.database import get_db, Database
from db.models import Agent
from core.inference import inference_engine

router = APIRouter(prefix="/api/agents", tags=["agents"])

class AgentBase(BaseModel):
    name: str
    description: str = ""
    system_prompt: str
    escalation_marker: str = "ESCALATE_TO_HUMAN"
    fallback_responses: str = "{}"
    is_active: int = 1

class AgentCreate(AgentBase):
    pass

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    escalation_marker: Optional[str] = None
    fallback_responses: Optional[str] = None
    is_active: Optional[int] = None

class AgentResponse(AgentBase):
    id: int

@router.get("", response_model=List[AgentResponse])
async def list_agents(db: Database = Depends(get_db)):
    agents = await db.get_all_agents()
    return agents

@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: int, db: Database = Depends(get_db)):
    agent = await db.get_agent(agent_id=agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent

@router.post("", response_model=AgentResponse)
async def create_agent(agent_in: AgentCreate, db: Database = Depends(get_db)):
    agent = Agent(**agent_in.dict())
    agent_id = await db.upsert_agent(agent)
    agent.id = agent_id
    return agent

@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(agent_id: int, agent_in: AgentUpdate, db: Database = Depends(get_db)):
    existing = await db.get_agent(agent_id=agent_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    update_data = agent_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(existing, field, value)
    
    await db.upsert_agent(existing)
    return existing

@router.post("/{agent_id}/activate")
async def activate_agent(agent_id: int, db: Database = Depends(get_db)):
    existing = await db.get_agent(agent_id=agent_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    await db.activate_agent(agent_id)
    await inference_engine.reload()
    return {"status": "success", "message": f"Agent {agent_id} activated"}

@router.post("/{agent_id}/reload")
async def reload_agent(agent_id: int):
    # This specifically reloads the inference engine's cache
    # If the engine is using a different agent_id, it might not affect it unless it's the active one
    await inference_engine.reload()
    return {"status": "success", "message": "Inference engine cache reloaded"}

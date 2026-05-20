from __future__ import annotations

from db.models import (
    Agent,
    AgentCapability,
    AgentDecision,
    AgentTemplate,
    row_to_agent,
    row_to_agent_capability,
    row_to_agent_decision,
    row_to_agent_template,
)
from db.repositories.base import BaseRepository


class AgentRepository(BaseRepository):
    async def get(self, agent_id: int | None = None, is_active: bool = True) -> Agent | None:
        if agent_id:
            row = await self._fetchone("SELECT * FROM agents WHERE id=$1", agent_id)
        elif is_active:
            row = await self._fetchone(
                "SELECT * FROM agents WHERE is_active=TRUE ORDER BY updated_at DESC LIMIT 1"
            )
        else:
            row = await self._fetchone("SELECT * FROM agents ORDER BY updated_at DESC LIMIT 1")
        return row_to_agent(row)

    async def get_all(self) -> list[Agent]:
        rows = await self._fetchall("SELECT * FROM agents ORDER BY name ASC")
        return [a for r in rows if (a := row_to_agent(r)) is not None]

    async def upsert(self, agent: Agent) -> int:
        if agent.id:
            await self._execute(
                """UPDATE agents SET name=$1, description=$2, system_prompt=$3,
                escalation_marker=$4, fallback_responses=$5, is_active=$6, updated_at=NOW()
                WHERE id=$7""",
                agent.name, agent.description, agent.system_prompt,
                agent.escalation_marker, agent.fallback_responses, agent.is_active, agent.id,
            )
            return agent.id
        return await self._insert_returning_id(
            """INSERT INTO agents (name, description, system_prompt, escalation_marker, fallback_responses, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (name) DO UPDATE SET
                description=excluded.description,
                system_prompt=excluded.system_prompt,
                escalation_marker=excluded.escalation_marker,
                fallback_responses=excluded.fallback_responses,
                is_active=excluded.is_active,
                updated_at=NOW()
            RETURNING id""",
            agent.name, agent.description, agent.system_prompt,
            agent.escalation_marker, agent.fallback_responses, agent.is_active,
        )

    async def activate(self, agent_id: int) -> None:
        await self._execute_transaction([
            ("UPDATE agents SET is_active=FALSE", ()),
            ("UPDATE agents SET is_active=TRUE WHERE id=$1", (agent_id,)),
        ])


class AgentDecisionRepository(BaseRepository):
    async def insert(self, decision: AgentDecision) -> int:
        return await self._insert_returning_id(
            """INSERT INTO agent_decisions
            (message_id, phone, sentiment, sentiment_score, confidence,
            llm_escalate, escalate_reason, history_count, agent_name, correlation_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id""",
            decision.message_id, decision.phone, decision.sentiment,
            decision.sentiment_score, decision.confidence, decision.llm_escalate,
            decision.escalate_reason, decision.history_count, decision.agent_name,
            decision.correlation_id,
        )

    async def get_for_phone(self, phone: str, limit: int = 50) -> list[AgentDecision]:
        rows = await self._fetchall(
            """SELECT ad.* FROM agent_decisions ad
            JOIN messages m ON ad.message_id = m.id
            WHERE m.phone = $1
            ORDER BY ad.created_at DESC LIMIT $2""",
            phone, limit,
        )
        return [d for r in rows if (d := row_to_agent_decision(r)) is not None]

    async def get_for_message(self, message_id: int) -> AgentDecision | None:
        row = await self._fetchone(
            "SELECT * FROM agent_decisions WHERE message_id=$1",
            message_id,
        )
        return row_to_agent_decision(row)


class AgentCapabilityRepository(BaseRepository):
    async def get_for_agent(self, agent_id: int) -> list[AgentCapability]:
        rows = await self._fetchall(
            "SELECT * FROM agent_capabilities WHERE agent_id=$1 ORDER BY capability_name",
            agent_id,
        )
        return [c for r in rows if (c := row_to_agent_capability(r)) is not None]

    async def upsert(self, ac: AgentCapability) -> int:
        row = await self._fetchone(
            """INSERT INTO agent_capabilities (agent_id, capability_name, is_active, config_json, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, NOW())
            ON CONFLICT (agent_id, capability_name) DO UPDATE SET
            is_active=excluded.is_active,
            config_json=excluded.config_json,
            updated_at=NOW()
            RETURNING id""",
            ac.agent_id, ac.capability_name, ac.is_active, ac.config_json,
        )
        return row["id"]  # type: ignore[index,no-any-return]
    async def delete(self, agent_id: int, capability_name: str) -> None:
        await self._execute(
            "DELETE FROM agent_capabilities WHERE agent_id=$1 AND capability_name=$2",
            agent_id, capability_name,
        )


class AgentTemplateRepository(BaseRepository):
    async def get_all(self) -> list[AgentTemplate]:
        rows = await self._fetchall(
            "SELECT id, name, description, system_prompt_template, capabilities, fallback_responses, created_at FROM agent_templates ORDER BY id"
        )
        return [t for r in rows if (t := row_to_agent_template(r)) is not None]

    async def get(self, template_id: int) -> AgentTemplate | None:
        row = await self._fetchone(
            "SELECT id, name, description, system_prompt_template, capabilities, fallback_responses, created_at FROM agent_templates WHERE id = $1",
            template_id,
        )
        return row_to_agent_template(row)

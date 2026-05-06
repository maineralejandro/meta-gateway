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
            row = await self._fetchone("SELECT * FROM agents WHERE id=?", (agent_id,))
        elif is_active:
            row = await self._fetchone(
                "SELECT * FROM agents WHERE is_active=1 ORDER BY updated_at DESC LIMIT 1"
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
                """UPDATE agents SET name=?, description=?, system_prompt=?,
                   escalation_marker=?, fallback_responses=?, is_active=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (
                    agent.name,
                    agent.description,
                    agent.system_prompt,
                    agent.escalation_marker,
                    agent.fallback_responses,
                    agent.is_active,
                    agent.id,
                ),
            )
            await self._commit()
            return agent.id
        else:
            return await self._insert_returning_id(
                """INSERT INTO agents (name, description, system_prompt, escalation_marker, fallback_responses, is_active)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    agent.name,
                    agent.description,
                    agent.system_prompt,
                    agent.escalation_marker,
                    agent.fallback_responses,
                    agent.is_active,
                ),
            )

    async def activate(self, agent_id: int) -> None:
        await self._execute_transaction(
            [
                ("UPDATE agents SET is_active=0", ()),
                ("UPDATE agents SET is_active=1 WHERE id=?", (agent_id,)),
            ]
        )


class AgentDecisionRepository(BaseRepository):
    async def insert(self, decision: AgentDecision) -> int:
        return await self._insert_returning_id(
            """INSERT INTO agent_decisions
            (message_id, phone, sentiment, sentiment_score, confidence,
            llm_escalate, escalate_reason, history_count, agent_name, correlation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision.message_id,
                decision.phone,
                decision.sentiment,
                decision.sentiment_score,
                decision.confidence,
                decision.llm_escalate,
                decision.escalate_reason,
                decision.history_count,
                decision.agent_name,
                decision.correlation_id,
            ),
        )

    async def get_for_phone(self, phone: str, limit: int = 50) -> list[AgentDecision]:
        rows = await self._fetchall(
            """SELECT ad.* FROM agent_decisions ad
            JOIN messages m ON ad.message_id = m.id
            WHERE m.phone = ?
            ORDER BY ad.created_at DESC LIMIT ?""",
            (phone, limit),
        )
        return [d for r in rows if (d := row_to_agent_decision(r)) is not None]

    async def get_for_message(self, message_id: int) -> AgentDecision | None:
        row = await self._fetchone(
            "SELECT * FROM agent_decisions WHERE message_id=?",
            (message_id,),
        )
        return row_to_agent_decision(row)


class AgentCapabilityRepository(BaseRepository):
    async def get_for_agent(self, agent_id: int) -> list[AgentCapability]:
        rows = await self._fetchall(
            "SELECT * FROM agent_capabilities WHERE agent_id=? ORDER BY capability_name",
            (agent_id,),
        )
        return [c for r in rows if (c := row_to_agent_capability(r)) is not None]

    async def upsert(self, ac: AgentCapability) -> int:
        return await self._insert_returning_id(
            """INSERT INTO agent_capabilities (agent_id, capability_name, is_active, config_json, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(agent_id, capability_name) DO UPDATE SET
                is_active=excluded.is_active,
                config_json=excluded.config_json,
                updated_at=CURRENT_TIMESTAMP""",
            (ac.agent_id, ac.capability_name, ac.is_active, ac.config_json),
        )

    async def delete(self, agent_id: int, capability_name: str) -> None:
        await self._execute_and_commit(
            "DELETE FROM agent_capabilities WHERE agent_id=? AND capability_name=?",
            (agent_id, capability_name),
        )


class AgentTemplateRepository(BaseRepository):
    async def get_all(self) -> list[AgentTemplate]:
        rows = await self._fetchall(
            "SELECT id, name, description, system_prompt_template, capabilities, fallback_responses, created_at FROM agent_templates ORDER BY id"
        )
        return [t for r in rows if (t := row_to_agent_template(r)) is not None]

    async def get(self, template_id: int) -> AgentTemplate | None:
        row = await self._fetchone(
            "SELECT id, name, description, system_prompt_template, capabilities, fallback_responses, created_at FROM agent_templates WHERE id = ?",
            (template_id,),
        )
        return row_to_agent_template(row)

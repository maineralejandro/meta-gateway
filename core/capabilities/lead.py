import json
from typing import Any, ClassVar

import structlog

from core.capabilities.base import BaseCapability

logger = structlog.get_logger()

DEFAULT_STAGES: list[str] = ["interesado", "calificado", "visita", "propuesta", "cerrado"]
DEFAULT_FIELDS: list[str] = ["presupuesto", "zona", "tipo_propiedad"]


class LeadCapability(BaseCapability):
    name = "lead"
    description = "Lead pipeline tracking with configurable stages and fields"
    config_schema: ClassVar[list[dict[str, Any]]] = [
        {"key": "stages", "type": "array", "label": "Pipeline Stages", "default": DEFAULT_STAGES},
        {"key": "fields", "type": "array", "label": "Lead Fields", "default": DEFAULT_FIELDS},
    ]
    PARALLEL_SAFE_TOOLS: ClassVar[set[str]] = {"lead_get"}
    SEQUENTIAL_TOOLS: ClassVar[set[str]] = {"lead_update_field", "lead_advance_stage"}

    _TOOL_DEFINITIONS: ClassVar[list[dict[str, Any]]] = [
        {
            "type": "function",
            "function": {
                "name": "lead_update_field",
                "description": (
                    "Llama esta funcion cuando el cliente proporcione informacion personal "
                    "que debas guardar (nombre, email, presupuesto, zona, etc.). "
                    "NO la llames si el cliente solo pregunta por el estado de su prospecto."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "description": "Nombre del campo (ej: nombre, email, presupuesto, zona)"},
                        "value": {"type": "string", "description": "Valor del campo"},
                    },
                    "required": ["field", "value"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "lead_advance_stage",
                "description": (
                    "Llama esta funcion cuando el cliente avance explicitamente a la siguiente "
                    "etapa del pipeline de ventas (ej: de interesado a calificado). "
                    "NO la llames sin confirmacion del avance."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "stage": {"type": "string", "description": "Etapa destino (ej: interesado, calificado, visita, propuesta, cerrado)"},
                    },
                    "required": ["stage"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "lead_get",
                "description": "Obtener la informacion actual del prospecto. Usar para ver que datos faltan antes de actualizar.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._leads: dict[str, dict[str, Any]] = {}
        self._loaded_phones: set[str] = set()

    def _get_stages(self) -> list[str]:
        val = self.config.get("stages", DEFAULT_STAGES)
        return val if isinstance(val, list) else DEFAULT_STAGES

    def _get_fields(self) -> list[str]:
        val = self.config.get("fields", DEFAULT_FIELDS)
        return val if isinstance(val, list) else DEFAULT_FIELDS

    def _stage_name(self, stage_key: str) -> str:
        stage_names: dict[str, str] = {
            "interesado": "Interesado",
            "calificado": "Calificado",
            "visita": "Visita",
            "propuesta": "Propuesta",
            "cerrado": "Cerrado",
        }
        return stage_names.get(stage_key, stage_key.capitalize())

    async def _ensure_loaded(self, phone: str) -> None:
        if phone in self._loaded_phones:
            return
        try:
            from db.database import get_db
            db = await get_db()
            row = await db.load_lead(phone)
            if row:
                self._leads[phone] = {
                    "stage": row["stage"],
                    "data": json.loads(row["data_json"]) if isinstance(row["data_json"], str) else {},
                }
        except Exception as e:
            logger.error("lead_load_error", phone=phone, error=str(e))
        self._loaded_phones.add(phone)

    async def _persist(self, phone: str) -> None:
        lead = self._leads.get(phone)
        try:
            from db.database import get_db
            db = await get_db()
            if lead:
                await db.upsert_lead(phone, lead["stage"], json.dumps(lead.get("data", {})))
            else:
                await db.upsert_lead(phone, "interesado", "{}")
        except Exception as e:
            logger.error("lead_persist_error", phone=phone, error=str(e))

    async def update_field(self, phone: str, field: str, value: str) -> None:
        await self._ensure_loaded(phone)
        if phone not in self._leads:
            self._leads[phone] = {"stage": "interesado", "data": {}}
        self._leads[phone]["data"][field] = value
        await self._persist(phone)
        logger.info("lead_field_updated", phone=phone, field=field, value=value)

    async def advance_stage(self, phone: str, stage: str) -> None:
        await self._ensure_loaded(phone)
        stages = self._get_stages()
        if stage not in stages:
            logger.warning("lead_invalid_stage", phone=phone, stage=stage, valid=stages)
            return
        if phone not in self._leads:
            self._leads[phone] = {"stage": "interesado", "data": {}}
        self._leads[phone]["stage"] = stage
        await self._persist(phone)
        logger.info("lead_stage_advanced", phone=phone, stage=stage)

    async def get_lead(self, phone: str) -> dict[str, Any] | None:
        await self._ensure_loaded(phone)
        return self._leads.get(phone)

    def _lead_state_dict(self, phone: str) -> dict[str, Any]:
        lead = self._leads.get(phone)
        if not lead:
            return {"stage": None, "data": {}}
        return {"stage": lead["stage"], "data": dict(lead.get("data", {}))}

    def get_tool_definitions(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        return list(self._TOOL_DEFINITIONS)

    def get_tool_names(self) -> set[str]:
        return {"lead_update_field", "lead_advance_stage", "lead_get"}

    async def execute_tool(
        self,
        name: str,
        args: dict[str, Any],
        phone: str,
        tool_call_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        if name == "lead_update_field":
            return await self._execute_update_field(args, phone)
        if name == "lead_advance_stage":
            return await self._execute_advance_stage(args, phone)
        if name == "lead_get":
            return await self._execute_get(phone)
        return {"success": False, "error": f"Unknown tool: {name}"}

    async def _execute_update_field(self, args: dict[str, Any], phone: str) -> dict[str, Any]:
        field = args.get("field", "")
        value = args.get("value", "")
        if not field:
            return {"success": False, "error": "field is required", "instruction": "Proporciona el nombre del campo a actualizar."}
        await self.update_field(phone, field, value)
        return {
            "success": True,
            "action": "field_updated",
            "field": field,
            "value": value,
            "lead_state": self._lead_state_dict(phone),
        }

    async def _execute_advance_stage(self, args: dict[str, Any], phone: str) -> dict[str, Any]:
        stage = args.get("stage", "")
        if not stage:
            return {"success": False, "error": "stage is required", "instruction": "Proporciona la etapa destino."}
        stages = self._get_stages()
        if stage not in stages:
            return {
                "success": False,
                "error": f"stage '{stage}' not found",
                "valid_stages": stages,
                "instruction": "Usa una de las etapas validas listadas arriba.",
            }
        await self.advance_stage(phone, stage)
        return {
            "success": True,
            "action": "stage_advanced",
            "stage": stage,
            "lead_state": self._lead_state_dict(phone),
        }

    async def _execute_get(self, phone: str) -> dict[str, Any]:
        await self._ensure_loaded(phone)
        return {
            "success": True,
            "action": "lead_retrieved",
            "lead_state": self._lead_state_dict(phone),
        }

    async def format_for_context(self, phone: str, config: dict[str, Any]) -> str | None:
        await self._ensure_loaded(phone)
        lead = self._leads.get(phone)
        if not lead:
            return None
        stage_display = self._stage_name(lead["stage"])
        lines = [
            "Lead del cliente:",
            f"- Etapa: {stage_display}",
        ]
        for key, value in lead.get("data", {}).items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    async def clear(self, phone: str, config: dict[str, Any]) -> None:
        self._leads.pop(phone, None)
        self._loaded_phones.discard(phone)

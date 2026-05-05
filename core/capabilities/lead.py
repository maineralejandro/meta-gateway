import json
import re
from typing import Any, ClassVar

import structlog

from core.capabilities.base import BaseCapability

logger = structlog.get_logger()

LEAD_UPDATE_RE = re.compile(r"\[LEAD_UPDATE:([a-z_0-9]+):([^\]]+)\]")
LEAD_STAGE_RE = re.compile(r"\[LEAD_STAGE:([a-z_0-9]+)\]")

DEFAULT_STAGES: list[str] = ["interesado", "calificado", "visita", "propuesta", "cerrado"]
DEFAULT_FIELDS: list[str] = ["presupuesto", "zona", "tipo_propiedad"]


class LeadCapability(BaseCapability):
    name = "lead"
    description = "Lead pipeline tracking with configurable stages and fields"
    config_schema: ClassVar[list[dict[str, Any]]] = [
        {"key": "stages", "type": "array", "label": "Pipeline Stages", "default": DEFAULT_STAGES},
        {"key": "fields", "type": "array", "label": "Lead Fields", "default": DEFAULT_FIELDS},
    ]
    tag_patterns: ClassVar[dict[str, re.Pattern[str]]] = {
        "LEAD_UPDATE": LEAD_UPDATE_RE,
        "LEAD_STAGE": LEAD_STAGE_RE,
    }

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

    async def parse_tags(self, phone: str, text: str, config: dict[str, Any]) -> str:
        for match in LEAD_UPDATE_RE.finditer(text):
            field, value = match.group(1), match.group(2)
            await self.update_field(phone, field, value)

        for match in LEAD_STAGE_RE.finditer(text):
            stage = match.group(1)
            await self.advance_stage(phone, stage)

        cleaned = LEAD_UPDATE_RE.sub("", text)
        cleaned = LEAD_STAGE_RE.sub("", cleaned)
        return cleaned.strip()

    async def clear(self, phone: str, config: dict[str, Any]) -> None:
        self._leads.pop(phone, None)
        self._loaded_phones.discard(phone)

    def get_prompt_instructions(self, config: dict[str, Any]) -> str:
        stages = self._get_stages()
        fields = self._get_fields()
        stages_str = ", ".join(stages)
        fields_str = ", ".join(fields)
        return (
            "GESTION DE LEADS (OBLIGATORIO):\n"
            "Cuando el cliente brinde informacion relevante, incluye al final de tu respuesta: "
            "[LEAD_UPDATE:campo:valor]\n"
            f"Campos validos: {fields_str}\n\n"
            "Cuando el lead avance de etapa: [LEAD_STAGE:etapa]\n"
            f"Etapas validas: {stages_str}\n\n"
            "Los tags NO son visibles para el cliente."
        )

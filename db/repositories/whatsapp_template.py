from __future__ import annotations

from typing import Any

from db.models import WhatsAppTemplate, row_to_whatsapp_template
from db.repositories.base import BaseRepository


class WhatsAppTemplateRepository(BaseRepository):

    async def create(self, t: WhatsAppTemplate) -> int:
        return await self._insert_returning_id(
            """INSERT INTO whatsapp_templates
            (agent_id, template_name, template_type, category, language, status,
             body_text, header_text, header_image_url, footer_text, buttons_json,
             meta_template_id, meta_quality_rating, rejection_reason)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            RETURNING id""",
            t.agent_id, t.template_name, t.template_type, t.category,
            t.language, t.status, t.body_text, t.header_text,
            t.header_image_url, t.footer_text, t.buttons_json,
            t.meta_template_id, t.meta_quality_rating, t.rejection_reason,
        )

    async def get(self, template_id: int) -> WhatsAppTemplate | None:
        row = await self._fetchone(
            "SELECT * FROM whatsapp_templates WHERE id=$1", template_id
        )
        return row_to_whatsapp_template(row)

    async def get_by_name(self, name: str) -> WhatsAppTemplate | None:
        row = await self._fetchone(
            "SELECT * FROM whatsapp_templates WHERE template_name=$1", name
        )
        return row_to_whatsapp_template(row)

    async def get_all(
        self, agent_id: int | None = None, status: str | None = None
    ) -> list[WhatsAppTemplate]:
        clauses: list[str] = []
        args: list[Any] = []
        idx = 1
        if agent_id is not None:
            clauses.append(f"agent_id=${idx}")
            args.append(agent_id)
            idx += 1
        if status is not None:
            clauses.append(f"status=${idx}")
            args.append(status)
            idx += 1
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = await self._fetchall(
            f"SELECT * FROM whatsapp_templates{where} ORDER BY template_name",
            *args,
        )
        return [r for r in (row_to_whatsapp_template(row) for row in rows) if r is not None]

    async def update(self, template_id: int, **fields: Any) -> None:
        if not fields:
            return
        sets: list[str] = []
        args: list[Any] = []
        idx = 1
        for k, v in fields.items():
            sets.append(f"{k}=${idx}")
            args.append(v)
            idx += 1
        sets.append(f"updated_at=${idx}")
        from datetime import UTC, datetime
        args.append(datetime.now(tz=UTC).isoformat())
        args.append(template_id)
        await self._execute(
            f"UPDATE whatsapp_templates SET {', '.join(sets)} WHERE id=${idx + 1}",
            *args,
        )

    async def delete(self, template_id: int) -> None:
        await self._execute("DELETE FROM whatsapp_templates WHERE id=$1", template_id)

    async def upsert_from_meta(self, meta_data: dict[str, Any]) -> int:
        name = meta_data.get("name", "")
        existing = await self.get_by_name(name)
        status = meta_data.get("status", "PENDING")
        if status == "APPROVED":
            status = "APPROVED"
        elif status in ("REJECTED", "PAUSED", "DISABLED"):
            status = status
        else:
            status = "PENDING"

        components = meta_data.get("components", [])
        body_text = ""
        header_text = None
        footer_text = None
        buttons: list[dict[str, Any]] = []
        for comp in components:
            ct = comp.get("type", "")
            if ct == "BODY":
                body_text = comp.get("text", "")
            elif ct == "HEADER":
                header_text = comp.get("text", "")
            elif ct == "FOOTER":
                footer_text = comp.get("text", "")
            elif ct == "BUTTONS":
                buttons.append(comp)

        import json
        if existing and existing.id is not None:
            await self.update(
                existing.id,
                status=status,
                body_text=body_text,
                header_text=header_text,
                footer_text=footer_text,
                buttons_json=json.dumps(buttons),
                meta_template_id=str(meta_data.get("id", "")),
                meta_quality_rating=meta_data.get("quality_rating"),
                rejection_reason=meta_data.get("rejection_reason"),
                template_type=meta_data.get("category", "UTILITY"),
                category=meta_data.get("category", "UTILITY"),
                language=meta_data.get("language", "es"),
            )
            return existing.id
        t = WhatsAppTemplate(
            template_name=name,
            template_type=meta_data.get("category", "UTILITY"),
            category=meta_data.get("category", "UTILITY"),
            language=meta_data.get("language", "es"),
            status=status,
            body_text=body_text,
            header_text=header_text,
            footer_text=footer_text,
            buttons_json=json.dumps(buttons),
            meta_template_id=str(meta_data.get("id", "")),
            meta_quality_rating=meta_data.get("quality_rating"),
            rejection_reason=meta_data.get("rejection_reason"),
        )
        return await self.create(t)

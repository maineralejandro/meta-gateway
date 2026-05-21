import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.database import close_db, get_db, init_db
from db.models import WhatsAppTemplate


async def seed_templates() -> None:
    await init_db()
    db = await get_db()

    templates = [
        WhatsAppTemplate(
            agent_id=1,
            template_name="greeting",
            template_type="UTILITY",
            category="UTILITY",
            language="es",
            status="APPROVED",
            body_text="Hola {{1}}, gracias por contactarnos.",
            buttons_json="[]"
        ),
        WhatsAppTemplate(
            agent_id=1,
            template_name="order_confirmation",
            template_type="UTILITY",
            category="UTILITY",
            language="es",
            status="APPROVED",
            body_text="Tu pedido ha sido confirmado. Total: {{1}}.",
            buttons_json="[]"
        ),
        WhatsAppTemplate(
            agent_id=1,
            template_name="delivery_update",
            template_type="UTILITY",
            category="UTILITY",
            language="es",
            status="APPROVED",
            body_text="Tu pedido está {{1}}. Entrega estimada: {{2}}.",
            buttons_json="[]"
        ),
        WhatsAppTemplate(
            agent_id=1,
            template_name="follow_up",
            template_type="MARKETING",
            category="MARKETING",
            language="es",
            status="APPROVED",
            body_text="Hola {{1}}, ¿necesitas ayuda con algo más?",
            buttons_json="[]"
        ),
        WhatsAppTemplate(
            agent_id=1,
            template_name="appointment_reminder",
            template_type="UTILITY",
            category="UTILITY",
            language="es",
            status="APPROVED",
            body_text="Recordatorio: tu cita es el {{1}} a las {{2}}.",
            buttons_json="[]"
        )
    ]

    print("Iniciando siembra de plantillas de WhatsApp...")
    for t in templates:
        existing = await db.whatsapp_templates.get_by_name(t.template_name)
        if existing:
            print(f"Plantilla '{t.template_name}' ya existe. Saltando...")
            continue

        template_id = await db.whatsapp_templates.create(t)
        print(f"Plantilla '{t.template_name}' creada con ID: {template_id}")

    await close_db()
    print("Siembra de plantillas completada con éxito.")

if __name__ == "__main__":
    asyncio.run(seed_templates())

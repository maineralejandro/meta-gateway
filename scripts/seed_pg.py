import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: I001
from core.config import settings


async def seed() -> None:
    conn = await asyncpg.connect(settings.DATABASE_URL, timeout=10)

    agent_id = await conn.fetchval("""
        INSERT INTO agents (name, description, system_prompt, escalation_marker, fallback_responses, is_active)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6)
        ON CONFLICT (name) DO UPDATE SET
            description=excluded.description,
            system_prompt=excluded.system_prompt,
            escalation_marker=excluded.escalation_marker,
            fallback_responses=excluded.fallback_responses,
            is_active=excluded.is_active,
            updated_at=NOW()
        RETURNING id
    """,
        'Default Agent',
        'Asistente virtual genérico',
        'Eres el asistente virtual de {{business_name}}. Responde en español, amable y directo.\n\nREGLAS:\n- El catálogo y precios disponibles se inyectan dinámicamente en tu contexto. NUNCA inventes productos ni precios. Usa SOLO los que aparecen en tu contexto o los que obtengas mediante las herramientas disponibles.\n- Si el cliente quiere cancelar, responde exactamente: ESCALATE_TO_HUMAN\n- Si el cliente está molesto o quejándose, responde exactamente: ESCALATE_TO_HUMAN\n- Si no entiendes la pregunta o tienes baja confianza, responde exactamente: ESCALATE_TO_HUMAN\n- Siempre confirma totales antes de cerrar un carrito.\n- NUNCA inventes items que el cliente no pidió. Solo calcula totales basándote en lo que el cliente realmente agregó al carrito.',
        'ESCALATE_TO_HUMAN',
        '{"price": "¿Qué producto te interesa? Puedo consultarte el precio de cualquier item.", "promo": "Pregunta por nuestras promociones del día!", "greeting": "Hola! Bienvenido. ¿En qué puedo ayudarte?", "default": "No estoy seguro de tu pregunta. ¿Podrías aclarar?"}',
        True,
    )
    print(f"Agent upserted: id={agent_id}")

    await conn.execute("""
        INSERT INTO agent_capabilities (agent_id, capability_name, is_active, config_json)
        VALUES ($1, $2, $3, $4::jsonb)
        ON CONFLICT (agent_id, capability_name) DO UPDATE SET
            is_active=excluded.is_active,
            config_json=excluded.config_json,
            updated_at=NOW()
    """,
        agent_id, 'cart', True, '{}',
    )
    print("Capability 'cart' upserted")

    templates = [
        (
            'retail',
            'Bot para venta de productos y servicios',
            'Eres el asistente virtual de {{business_name}}. Vendes: {{products}}. Responde en español, amable y directo.',
            '[{"name": "cart", "config": {"catalog_source": "db", "currency": "CLP"}}]',
            '{"greeting": "¡Hola! ¿En qué puedo ayudarte?", "default": "¿En qué puedo ayudarte?"}',
        ),
        (
            'dentista',
            'Bot para consulta dental',
            'Eres la asistente virtual de {{business_name}}. Ayudas a los pacientes a agendar citas, consultar horarios y responder preguntas sobre servicios dentales.',
            '[{"name": "appointment", "config": {"slot_duration_minutes": 30, "services": [{"key": "limpieza", "name": "Limpieza dental"}, {"key": "control", "name": "Control general"}, {"key": "blanqueamiento", "name": "Blanqueamiento"}]}}]',
            '{"greeting": "¡Hola! ¿Deseas agendar una cita?", "default": "¿En qué puedo ayudarte?"}',
        ),
        (
            'gym',
            'Bot para gimnasio',
            'Eres la asistente virtual de {{business_name}}. Ayudas a los miembros con planes, horarios y estado de membresía.',
            '[{"name": "membership", "config": {"allow_free_trial": true, "trial_days": 7}}]',
            '{"greeting": "¡Hola! ¿Te interesa conocer nuestros planes?", "default": "¿En qué puedo ayudarte?"}',
        ),
        (
            'inmobiliaria',
            'Bot para inmobiliaria',
            'Eres la asistente virtual de {{business_name}}. Ayudas a los clientes a encontrar propiedades según sus necesidades.',
            '[{"name": "lead", "config": {"stages": ["interesado", "calificado", "visita", "propuesta", "cerrado"], "fields": ["presupuesto", "zona", "tipo_propiedad", "dormitorios"]}}]',
            '{"greeting": "¡Hola! ¿Buscas una propiedad?", "default": "¿En qué puedo ayudarte?"}',
        ),
    ]

    for name, desc, prompt, caps, fallback in templates:
        await conn.execute("""
            INSERT INTO agent_templates (name, description, system_prompt_template, capabilities, fallback_responses)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
            ON CONFLICT (name) DO UPDATE SET
                description=excluded.description,
                system_prompt_template=excluded.system_prompt_template,
                capabilities=excluded.capabilities,
                fallback_responses=excluded.fallback_responses
        """,
            name, desc, prompt, caps, fallback,
        )
    print(f"Templates upserted: {len(templates)}")

    await conn.close()
    print("Seed complete")


if __name__ == "__main__":
    asyncio.run(seed())

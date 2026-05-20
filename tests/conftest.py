import os
import socket

collect_ignore_glob = ["sqlite_legacy/*"]


def _detect_pg_port() -> str:
    for port in (54322,):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("localhost", port)) == 0:
                return str(port)
    return "54322"


os.environ.setdefault("DATABASE_URL", f"postgresql://postgres:postgres@localhost:{_detect_pg_port()}/postgres")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test-token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123456")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_verify")
os.environ.setdefault("LLM_API_KEY", "nvapi-REPLACE_ME")
os.environ.setdefault("DASHBOARD_TOKEN", "test_dashboard_token")
os.environ.setdefault("SKIP_STARTUP_VALIDATION", "true")
os.environ.setdefault("META_APP_SECRET", "test_secret")

import pytest  # noqa: E402

from core.config import settings  # noqa: E402

_HERMES_TABLES = [
    "promotion_items",
    "promotions",
    "catalog_options",
    "catalog_item_variants",
    "catalog_items",
    "carts",
    "agent_decisions",
    "escalation_events",
    "turns",
    "messages",
    "conversation_memory",
    "agent_capabilities",
    "agent_templates",
    "sessions",
    "conversations",
    "agents",
    "inference_traces",
    "appointments",
    "memberships",
    "leads",
]


def _ensure_alembic() -> None:
    from pathlib import Path

    from alembic.config import Config as AlembicConfig

    from alembic import command

    alembic_cfg = AlembicConfig()
    alembic_cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    command.upgrade(alembic_cfg, "head")


_ensure_alembic()


@pytest.fixture(autouse=True)
async def pg_clean():
    from db.engine import _pool as _check_pool
    from db.engine import close_pool, create_pool, get_pool

    if _check_pool is not None:
        await close_pool()
    await create_pool()
    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            for t in _HERMES_TABLES:
                await conn.execute(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE")
            await conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_meta_id ON messages(meta_message_id)"
            )
            await conn.execute(
                "INSERT INTO agents (id, name, system_prompt, escalation_marker, fallback_responses, is_active) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                1, "Default Agent",
                "Eres el asistente. Usa herramientas cart_add, cart_remove, cart_clear.",
                "ESCALATE_TO_HUMAN", "{}", True,
            )
            await conn.execute(
                "INSERT INTO agent_capabilities (agent_id, capability_name, is_active, config_json) "
                "VALUES ($1, $2, $3, $4::jsonb)",
                1, "cart", True, "{}",
            )
            await conn.execute("SELECT setval('agents_id_seq', 1, true)")
        await conn.executemany(
            "INSERT INTO agent_templates (name, description, system_prompt_template, capabilities, fallback_responses) "
            "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)",
            [
                ("retail", "Bot para venta de productos y servicios",
                 "Eres el asistente virtual de {{business_name}}. Vendes: {{products}}. Responde en español, amable y directo.",
                 '[{"name": "cart", "config": {"catalog_source": "db", "currency": "CLP"}}]',
                 '{"greeting": "¡Hola! ¿En qué puedo ayudarte?", "default": "¿En qué puedo ayudarte?"}'),
                ("dentista", "Bot para consulta dental",
                 "Eres la asistente virtual de {{business_name}}. Ayudas a los pacientes a agendar citas, consultar horarios y responder preguntas sobre servicios dentales.",
                 '[{"name": "appointment", "config": {"slot_duration_minutes": 30, "services": [{"key": "limpieza", "name": "Limpieza dental"}, {"key": "control", "name": "Control general"}, {"key": "blanqueamiento", "name": "Blanqueamiento"}]}}]',
                 '{"greeting": "¡Hola! ¿Deseas agendar una cita?", "default": "¿En qué puedo ayudarte?"}'),
                ("gym", "Bot para gimnasio",
                 "Eres la asistente virtual de {{business_name}}. Ayudas a los miembros con planes, horarios y estado de membresía.",
                 '[{"name": "membership", "config": {"allow_free_trial": true, "trial_days": 7}}]',
                 '{"greeting": "¡Hola! ¿Te interesa conocer nuestros planes?", "default": "¿En qué puedo ayudarte?"}'),
                ("inmobiliaria", "Bot para inmobiliaria",
                 "Eres la asistente virtual de {{business_name}}. Ayudas a los clientes a encontrar propiedades según sus necesidades.",
                 '[{"name": "lead", "config": {"stages": ["interesado", "calificado", "visita", "propuesta", "cerrado"], "fields": ["presupuesto", "zona", "tipo_propiedad", "dormitorios"]}}]',
                 '{"greeting": "¡Hola! ¿Buscas una propiedad?", "default": "¿En qué puedo ayudarte?"}'),
            ],
        )
        yield
    await close_pool()

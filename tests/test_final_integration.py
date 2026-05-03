import asyncio
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from core.config import settings
from core.memory import memory_manager
from core.security import rate_limiter
from db.database import close_db, db, init_db
from routers.webhook import receive_webhook


# Mock meta_client to avoid real API calls
@pytest.fixture(autouse=True)
def mock_meta_client():
    with patch("core.hitl_router.meta_client.send_text", new_callable=AsyncMock) as m:
        m.return_value = {"status": "success"}
        yield m

@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_integration_db():
    # Setup test DB
    import random
    suffix = random.randint(10000, 99999)
    test_db = f"./tests/data/final_integration_{suffix}.db"
    settings.DB_PATH = test_db
    settings.META_APP_SECRET = "integration_secret"
    settings.SKIP_STARTUP_VALIDATION = True

    os.makedirs("./tests/data", exist_ok=True)
    if os.path.exists(test_db):
        os.remove(test_db)

    await init_db()
    with open("db/schema.sql") as f:
        schema = f.read()
        conn = await db._get_conn()
        await conn.execute("PRAGMA foreign_keys=OFF")
        await conn.executescript(schema)
        await conn.execute("PRAGMA foreign_keys=ON")
        await db.commit()

    # Insert a default agent (INSERT OR REPLACE in case seed already created id=1)
    await db.execute(
        "INSERT OR REPLACE INTO agents (id, name, system_prompt, escalation_marker) VALUES (1, 'Hermes Bot', 'Eres un bot de ventas.', 'ESCALATE_TO_HUMAN')"
    )
    await db.commit()

    yield
    await close_db()

def create_meta_request(body_dict, secret="integration_secret"):
    body_bytes = json.dumps(body_dict).encode("utf-8")
    signature = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()

    request = MagicMock()
    request.body = AsyncMock(return_value=body_bytes)
    request.headers = {"X-Hub-Signature-256": f"sha256={signature}"}
    return request, body_bytes

@pytest.mark.asyncio
async def test_full_conversation_lifecycle():
    phone = "56912345678"

    # 1. Primer mensaje: Verifica Firma y Crea Sesión
    webhook_data = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": phone,
                        "id": "meta_id_1",
                        "text": {"body": "Hola, quiero información de precios"},
                        "type": "text"
                    }]
                }
            }]
        }]
    }

    request, _ = create_meta_request(webhook_data)

    # Procesar webhook
    # Patchamos el router para esperar que termine el procesamiento async si es necesario
    # Pero receive_webhook retorna inmediatamente lanzando una tarea.
    # Para el test, vamos a llamar a la lógica interna o esperar un poco.

    with patch("routers.webhook._safe_process", new_callable=AsyncMock) as mock_process:
        response = await receive_webhook(request)
        assert response["status"] == "processing"
        await asyncio.sleep(0)
        mock_process.assert_called_once()

    # Verificar que se creó la sesión en DB
    conv = await db.get_conversation(phone)
    assert conv is not None
    assert conv.current_session_id is not None
    session_id_1 = conv.current_session_id

    # 2. Simular 20 mensajes para gatillar Memoria por Capas (Summarization)
    # Vamos a insertar mensajes directamente para ahorrar tiempo
    for i in range(20):
        await db.execute(
            "INSERT INTO messages (phone, direction, source, text, session_id) VALUES (?, 'inbound', 'customer', ?, ?)",
            (phone, f"Mensaje extra {i}", session_id_1)
        )
    await db.commit()

    # Forzar resumen mockeando el cliente de OpenAI
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({
            "summary": "El cliente busca precios.",
            "key_facts": ["Interesado en promociones"]
        })))
    ]

    with patch.object(memory_manager._llm, "chat_completion", return_value=mock_response), \
         patch.object(memory_manager._llm, "get_client", return_value=MagicMock()):
        await memory_manager.maybe_summarize(phone)

    # Verificar que hay memoria
    memory = await db.get_memory(phone)
    assert memory is not None
    assert memory.total_messages_summarized > 0

    # 3. Verificar Rate Limiting
    # El rate limiter es global en el módulo core.security
    rate_limiter.max_per_minute = 2
    rate_limiter.requests[phone] = [time.time(), time.time()] # Simular 2 previos

    rate_limit_data = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": phone,
                        "id": "meta_id_ratelimit",
                        "text": {"body": "Hola de nuevo"},
                        "type": "text"
                    }]
                }
            }]
        }]
    }
    request_limit, _ = create_meta_request(rate_limit_data)
    response_limit = await receive_webhook(request_limit)
    assert response_limit == {"status": "rate_limited"}

    # Reset rate limiter para seguir
    rate_limiter.requests[phone] = []

    # 4. Simular Timeout de Sesión (4 horas después)
    # Retroceder el last_message_at de la conversación
    past_time = (datetime.now(UTC) - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
    await db.execute("UPDATE conversations SET last_message_at=? WHERE phone=?", (past_time, phone))
    await db.commit()

    # Al pedir una sesión nueva (vía webhook), debería cerrar la vieja y crear una nueva
    timeout_data = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": phone,
                        "id": "meta_id_timeout",
                        "text": {"body": "Hola de nuevo"},
                        "type": "text"
                    }]
                }
            }]
        }]
    }
    request_new, _ = create_meta_request(timeout_data)
    await receive_webhook(request_new)

    conv_after = await db.get_conversation(phone)
    assert conv_after.current_session_id != session_id_1
    assert conv_after.current_session_id is not None

    # Verificar que la sesión vieja está cerrada en la tabla sessions
    old_session = await db.fetchone("SELECT * FROM sessions WHERE id=?", (session_id_1,))
    assert old_session["ended_at"] is not None
    assert old_session["end_reason"] == "timeout"

    # 5. Verificar Sanitización en Output
    from core.security import sanitize_llm_output
    dirty_text = "Respuesta muy larga... " + ("X" * 2100) + " \x00"
    clean_text = sanitize_llm_output(dirty_text)
    assert len(clean_text) <= 2000
    assert "\x00" not in clean_text

    print("\n[OK] PRUEBA DE INTEGRACION FINAL EXITOSA")

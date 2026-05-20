import asyncio
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.memory import memory_manager
from core.security import rate_limiter
from db.database import db
from routers.webhook import receive_webhook


@pytest.fixture(autouse=True)
def mock_meta_client():
    with patch("core.hitl_router.meta_client.send_text", new_callable=AsyncMock) as m:
        m.return_value = {"status": "success"}
        yield m

def create_meta_request(body_dict, secret="test_secret"):
    body_bytes = json.dumps(body_dict).encode("utf-8")
    signature = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()

    request = MagicMock()
    request.body = AsyncMock(return_value=body_bytes)
    request.headers = {"X-Hub-Signature-256": f"sha256={signature}"}
    return request, body_bytes

@pytest.mark.asyncio
async def test_full_conversation_lifecycle():
    phone = "56912345678"

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

    with patch("routers.webhook.turn_builder") as mock_tb:
        mock_tb.debounce = AsyncMock()
        response = await receive_webhook(request)
        assert response["status"] == "processing"
        await asyncio.sleep(0)
        mock_tb.debounce.assert_called_once()

    conv = await db.get_conversation(phone)
    assert conv is not None
    assert conv.current_session_id is not None
    session_id_1 = conv.current_session_id

    for i in range(20):
        await db.execute(
            "INSERT INTO turns (phone, user_text, assistant_text) VALUES ($1, $2, $3)",
            phone, f"Mensaje extra {i}", f"Respuesta {i}",
        )

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

    memory = await db.get_memory(phone)
    assert memory is not None
    assert memory.total_messages_summarized > 0

    rate_limiter.max_per_minute = 2
    rate_limiter.requests[phone] = [time.time(), time.time()]

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

    rate_limiter.requests[phone] = []

    past_time = datetime.now(UTC) - timedelta(hours=5)
    await db.execute("UPDATE conversations SET last_message_at=$1 WHERE phone=$2", past_time, phone)

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

    old_session = await db.fetchone("SELECT * FROM sessions WHERE id=$1", session_id_1)
    assert old_session["ended_at"] is not None
    assert old_session["end_reason"] == "timeout"

    from core.security import sanitize_llm_output
    dirty_text = "Respuesta muy larga... " + ("X" * 2100) + " \x00"
    clean_text = sanitize_llm_output(dirty_text)
    assert len(clean_text) <= 2000
    assert "\x00" not in clean_text

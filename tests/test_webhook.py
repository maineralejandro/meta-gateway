import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_signature(secret: str, body: bytes) -> str:
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_deps():
    with patch("routers.webhook.verify_meta_signature", new_callable=AsyncMock, return_value=True), \
         patch("routers.webhook.rate_limiter") as mock_rl, \
         patch("routers.webhook.session_manager") as mock_sm, \
         patch("routers.webhook.turn_builder") as mock_tb, \
         patch("routers.webhook.get_db") as mock_get_db, \
         patch("routers.webhook.emit", new_callable=AsyncMock), \
         patch("routers.webhook.WEBHOOK_DUPLICATES", MagicMock()), \
         patch("routers.webhook.RATE_LIMITS", MagicMock()), \
         patch("routers.webhook.meta_client") as mock_mc:
        mock_rl.is_allowed.return_value = True
        mock_sm.get_or_create_session = AsyncMock(return_value=1)
        mock_tb.debounce = AsyncMock()
        mock_mc.mark_read = AsyncMock(return_value={"success": True})
        mock_mc.mark_read_with_typing = AsyncMock(return_value={"success": True})

        mock_db = MagicMock()
        mock_row = {"state": "BOT_ACTIVE", "requires_human_review": False}
        mock_db.fetchone = AsyncMock(return_value=mock_row)
        mock_db.insert_message_and_touch_conversation = AsyncMock(return_value=1)
        mock_db.increment_session_message_count = AsyncMock()
        mock_db.create_conversation = AsyncMock()
        mock_db.update_conversation_state = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_get_db.return_value = mock_db

        yield {
            "db": mock_db,
            "turn_builder": mock_tb,
            "session_manager": mock_sm,
            "rate_limiter": mock_rl,
            "meta_client": mock_mc,
        }


def test_verify_webhook_success(client):
    with patch("routers.webhook.settings") as mock_settings:
        mock_settings.WHATSAPP_VERIFY_TOKEN = "test-verify"
        response = client.get("/webhook/whatsapp", params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test-verify",
            "hub.challenge": "challenge-123",
        })
    assert response.status_code == 200
    assert response.text == "challenge-123"


def test_verify_webhook_invalid_token(client):
    with patch("routers.webhook.settings") as mock_settings:
        mock_settings.WHATSAPP_VERIFY_TOKEN = "test-verify"
        response = client.get("/webhook/whatsapp", params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-123",
        })
    assert response.status_code == 403


def test_receive_webhook_text_message(client, mock_deps):
    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_test_001",
                        "type": "text",
                        "text": {"body": "Hola, quiero un menú"},
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "processing"


def test_receive_webhook_rate_limited(client, mock_deps):
    mock_deps["rate_limiter"].is_allowed.return_value = False

    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_test_002",
                        "type": "text",
                        "text": {"body": "spam"},
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "rate_limited"


def test_receive_webhook_duplicate(client, mock_deps):
    mock_deps["db"].insert_message_and_touch_conversation = AsyncMock(
        side_effect=Exception("UNIQUE constraint failed: meta_message_id")
    )

    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_dup",
                        "type": "text",
                        "text": {"body": "Hola"},
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"


def test_receive_webhook_human_only(client, mock_deps):
    mock_deps["db"].fetchone = AsyncMock(return_value={"state": "HUMAN_ONLY", "requires_human_review": False})

    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_human",
                        "type": "text",
                        "text": {"body": "Necesito ayuda"},
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "pending_human"


def test_receive_webhook_pending_approval(client, mock_deps):
    mock_deps["db"].fetchone = AsyncMock(return_value={"state": "PENDING_APPROVAL", "requires_human_review": False})

    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_pending",
                        "type": "text",
                        "text": {"body": "Hola"},
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval"


def test_receive_webhook_new_conversation(client, mock_deps):
    mock_deps["db"].fetchone = AsyncMock(return_value=None)

    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56999999999",
                        "id": "wamid_new",
                        "type": "text",
                        "text": {"body": "Hola"},
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "processing"


def test_receive_webhook_image_message(client, mock_deps):
    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_img",
                        "type": "image",
                        "image": {"id": "media_id_123"},
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "processing"


def test_receive_webhook_location_message(client, mock_deps):
    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_loc",
                        "type": "location",
                        "location": {
                            "name": "Home",
                            "latitude": -33.45,
                            "longitude": -70.67,
                        },
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200


def test_receive_webhook_status_update(client, mock_deps):
    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "status": "delivered",
                        "id": "wamid_status",
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_receive_webhook_empty_entries(client, mock_deps):
    body = {"entry": []}
    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_receive_webhook_requires_human_review(client, mock_deps):
    mock_deps["db"].fetchone = AsyncMock(return_value={"state": "BOT_ACTIVE", "requires_human_review": True})

    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_review",
                        "type": "text",
                        "text": {"body": "Ayuda"},
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "pending_human"


def test_receive_webhook_invalid_signature(client):
    with patch("routers.webhook.verify_meta_signature", new_callable=AsyncMock, return_value=False):
        response = client.post("/webhook/whatsapp", json={"entry": []})
        assert response.status_code == 403


def test_receive_webhook_marks_read_with_typing(client, mock_deps):
    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_read_test",
                        "type": "text",
                        "text": {"body": "Hola"},
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    mock_deps["meta_client"].mark_read_with_typing.assert_called_once_with("wamid_read_test")


def test_receive_webhook_mark_read_failure_doesnt_block(client, mock_deps):
    mock_deps["meta_client"].mark_read_with_typing = AsyncMock(side_effect=Exception("API error"))

    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_fail_test",
                        "type": "text",
                        "text": {"body": "Hola"},
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "processing"


def test_receive_webhook_interactive_button_reply(client, mock_deps):
    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_btn_001",
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {"id": "yes", "title": "Sí"},
                        },
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "processing"
    call_args = mock_deps["db"].insert_message_and_touch_conversation.call_args
    assert call_args[1].get("text") == "Sí" or call_args[0][3] == "Sí"
    assert call_args[1].get("media_type") == "interactive_button" or call_args[1].get("media_url") == "yes"


def test_receive_webhook_interactive_list_reply(client, mock_deps):
    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_list_001",
                        "type": "interactive",
                        "interactive": {
                            "type": "list_reply",
                            "list_reply": {"id": "frutilla", "title": "Frutilla 1kg"},
                        },
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "processing"
    call_args = mock_deps["db"].insert_message_and_touch_conversation.call_args
    assert call_args[1].get("text") == "Frutilla 1kg" or call_args[0][3] == "Frutilla 1kg"


def test_receive_webhook_continue_with_bot_button(client, mock_deps):
    mock_deps["db"].fetchone = AsyncMock(return_value={"state": "PENDING_APPROVAL", "requires_human_review": False})

    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_continue",
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {"id": "continue_with_bot", "title": "Seguir con el bot"},
                        },
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "processing"
    mock_deps["db"].update_conversation_state.assert_called_once_with(
        "56912345678", "BOT_ACTIVE", requires_human_review=False
    )


def test_receive_webhook_status_persisted(client, mock_deps):
    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "status": "delivered",
                        "id": "wamid_status_002",
                        "recipient_id": "56912345678",
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    mock_deps["db"].execute.assert_called_once()


def test_receive_webhook_category_list_reply(client, mock_deps):
    body = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56912345678",
                        "id": "wamid_cat_001",
                        "type": "interactive",
                        "interactive": {
                            "type": "list_reply",
                            "list_reply": {"id": "category_food", "title": "Comida"},
                        },
                    }]
                }
            }]
        }]
    }

    response = client.post("/webhook/whatsapp", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "processing"
    call_args = mock_deps["db"].insert_message_and_touch_conversation.call_args
    text = call_args[1].get("text") or call_args[0][3]
    assert "categoria" in text.lower()
    assert "Comida" in text

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from db.models import AgentDecision, Message

AUTH_HEADERS = {"Authorization": "Bearer test_dashboard_token"}


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_deps():
    mock_db = MagicMock()
    mock_db.get_messages = AsyncMock(return_value=[
        Message(id=1, phone="56911111111", direction="inbound",
                source="customer", text="Hola"),
    ])
    mock_db.get_conversation = AsyncMock(return_value=None)
    mock_db.insert_message = AsyncMock()
    mock_db.execute_transaction = AsyncMock()
    mock_db.increment_session_message_count = AsyncMock()
    mock_db.get_decisions = AsyncMock(return_value=[
        AgentDecision(id=1, message_id=1, phone="56911111111"),
    ])
    mock_db.get_decision_for_message = AsyncMock(return_value=AgentDecision(
        id=1, message_id=1, phone="56911111111",
    ))

    mock_mc = MagicMock()
    mock_mc.send_text = AsyncMock(return_value={"messages": [{"id": "wamid1"}]})

    with patch("routers.messages.get_db", return_value=mock_db), \
         patch("routers.messages.meta_client", mock_mc), \
         patch("routers.messages.emit", new_callable=AsyncMock), \
         patch("routers.messages.MESSAGES_SENT", MagicMock()):
        yield {"db": mock_db, "meta_client": mock_mc}


def test_get_messages(client):
    response = client.get("/api/messages/56911111111", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["text"] == "Hola"


def test_get_messages_with_limit(client):
    response = client.get("/api/messages/56911111111?limit=10", headers=AUTH_HEADERS)
    assert response.status_code == 200


def test_send_message_success(client):
    response = client.post("/api/messages/send", json={
        "phone": "56911111111",
        "message": "Hola desde el dashboard",
    }, headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_send_message_meta_error(client, mock_deps):
    mock_deps["meta_client"].send_text = AsyncMock(return_value={"error": True, "status": 500})

    response = client.post("/api/messages/send", json={
        "phone": "56911111111",
        "message": "Hola",
    }, headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "meta_error"


def test_send_message_with_session(client, mock_deps):
    mock_conv = MagicMock()
    mock_conv.current_session_id = "42"
    mock_deps["db"].get_conversation = AsyncMock(return_value=mock_conv)

    response = client.post("/api/messages/send", json={
        "phone": "56911111111",
        "message": "Hola",
    }, headers=AUTH_HEADERS)
    assert response.status_code == 200
    mock_deps["db"].increment_session_message_count.assert_called_once_with("42")


def test_send_message_without_session(client, mock_deps):
    mock_deps["db"].get_conversation = AsyncMock(return_value=None)
    response = client.post("/api/messages/send", json={
        "phone": "56911111111",
        "message": "Hola",
    }, headers=AUTH_HEADERS)
    assert response.status_code == 200
    mock_deps["db"].increment_session_message_count.assert_not_called()


def test_get_decisions(client):
    response = client.get("/api/messages/56911111111/decisions", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1


def test_get_decision_for_message_found(client, mock_deps):
    mock_deps["db"].get_decision_for_message = AsyncMock(return_value=AgentDecision(
        id=1, message_id=1, phone="56911111111",
    ))
    response = client.get("/api/messages/56911111111/decisions/1", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 1


def test_get_decision_for_message_not_found(client, mock_deps):
    mock_deps["db"].get_decision_for_message = AsyncMock(return_value=None)
    response = client.get("/api/messages/56911111111/decisions/999", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "error" in data


def test_send_message_invalid_body(client):
    response = client.post("/api/messages/send", json={"phone": "56911111111"}, headers=AUTH_HEADERS)
    assert response.status_code == 422

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.config import settings


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Hermes" in response.text


def test_health_check_ok(client):
    with patch("main.meta_client") as mock_mc:
        mock_mc.health_check = AsyncMock(return_value={
            "connected": True, "status_code": 200, "error": None,
        })

        response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["meta_api"]["connected"] is True


def test_health_check_degraded(client):
    with patch("main.meta_client") as mock_mc:
        mock_mc.health_check = AsyncMock(return_value={
            "connected": False, "status_code": None, "error": "No token",
        })

        response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "hermes_info" in response.text


def test_token_auth_middleware_blocks_unauthorized(client):
    response = client.get("/api/conversations")
    assert response.status_code == 401


def test_token_auth_middleware_allows_exempt_paths(client):
    response = client.get("/")
    assert response.status_code == 200


def test_token_auth_middleware_allows_webhook(client):
    response = client.get("/webhook/whatsapp")
    assert response.status_code != 401


def test_token_auth_middleware_allows_authorized(client):
    with patch("routers.conversations.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.get_all_conversations = AsyncMock(return_value=[])
        mock_get_db.return_value = mock_db
        response = client.get(
            "/api/conversations",
            headers={"Authorization": f"Bearer {settings.DASHBOARD_TOKEN}"},
        )
    assert response.status_code == 200


def test_options_bypasses_auth(client):
    response = client.options("/api/conversations")
    assert response.status_code != 401


def test_api_rate_limit_allows_exempt(client):
    response = client.get("/api/health")
    assert response.status_code == 200


def test_cors_no_credentials_with_wildcard_origin(client):
    response = client.options(
        "/api/conversations",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-credentials", "").lower() != "true"

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.config import settings


@pytest.fixture
async def client():
    from main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_home_page(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "Default Agent" in response.text


@pytest.mark.asyncio
async def test_health_check_ok(client):
    with patch("main.meta_client") as mock_mc:
        mock_mc.health_check = AsyncMock(return_value={
            "connected": True, "status_code": 200, "error": None,
        })
        mock_mc.check_token_health = AsyncMock(return_value={
            "valid": True, "type": "USER", "expires_at": 1779235200, "remaining_min": 108, "scopes": ["whatsapp_business_messaging"],
        })

        response = await client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["meta_api"]["connected"] is True


@pytest.mark.asyncio
async def test_health_check_degraded(client):
    with patch("main.meta_client") as mock_mc:
        mock_mc.health_check = AsyncMock(return_value={
            "connected": False, "status_code": None, "error": "No token",
        })
        mock_mc.check_token_health = AsyncMock(return_value={
            "valid": False, "error": "No token",
        })

        response = await client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_metrics_endpoint(client):
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "hermes_info" in response.text


@pytest.mark.asyncio
async def test_token_auth_middleware_blocks_unauthorized(client):
    response = await client.get("/api/conversations")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_auth_middleware_allows_exempt_paths(client):
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_token_auth_middleware_allows_webhook(client):
    response = await client.get("/webhook/whatsapp")
    assert response.status_code != 401


@pytest.mark.asyncio
async def test_token_auth_middleware_allows_authorized(client):
    with patch("routers.conversations.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.get_all_conversations = AsyncMock(return_value=[])
        mock_get_db.return_value = mock_db
        response = await client.get(
            "/api/conversations",
            headers={"Authorization": f"Bearer {settings.DASHBOARD_TOKEN}"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_options_bypasses_auth(client):
    response = await client.options("/api/conversations")
    assert response.status_code != 401


@pytest.mark.asyncio
async def test_api_rate_limit_allows_exempt(client):
    response = await client.get("/api/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_cors_no_credentials_with_wildcard_origin(client):
    response = await client.options(
        "/api/conversations",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-credentials", "").lower() != "true"

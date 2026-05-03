from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.meta_client import MetaAPIClient


@pytest.fixture
def client():
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v18.0/123456"
    c.headers = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}
    c._client = None
    return c


@pytest.mark.asyncio
async def test_send_text_success(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid123"}]}
    mock_httpx.post.return_value = mock_resp

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.send_text("56912345678", "Hello")

    assert "error" not in result
    assert result["messages"][0]["id"] == "wamid123"


@pytest.mark.asyncio
async def test_send_text_http_error(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    mock_httpx.post.return_value = mock_resp

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.send_text("56912345678", "Hello")

    assert result["error"] is True
    assert result["status"] == 401


@pytest.mark.asyncio
async def test_send_message_alias(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True}
    mock_httpx.post.return_value = mock_resp

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.send_message("56912345678", "Hello")

    assert "error" not in result


@pytest.mark.asyncio
async def test_health_check_success(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_httpx.get.return_value = mock_resp

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.health_check()

    assert result["connected"] is True
    assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_health_check_no_token(client):
    from core.config import settings
    old = settings.WHATSAPP_ACCESS_TOKEN
    settings.WHATSAPP_ACCESS_TOKEN = ""
    try:
        result = await client.health_check()
    finally:
        settings.WHATSAPP_ACCESS_TOKEN = old

    assert result["connected"] is False
    assert "No access token" in result["error"]


@pytest.mark.asyncio
async def test_health_check_exception(client):
    mock_httpx = AsyncMock()
    mock_httpx.get.side_effect = ConnectionError("DNS failed")

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.health_check()

    assert result["connected"] is False
    assert result["status_code"] is None
    assert "DNS failed" in result["error"]


@pytest.mark.asyncio
async def test_close_client(client):
    mock_httpx = MagicMock()
    mock_httpx.is_closed = False
    mock_httpx.aclose = AsyncMock()
    client._client = mock_httpx

    await client.close()
    mock_httpx.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_close_no_client(client):
    client._client = None
    await client.close()


@pytest.mark.asyncio
async def test_close_already_closed(client):
    mock_httpx = MagicMock()
    mock_httpx.is_closed = True
    mock_httpx.aclose = AsyncMock()
    client._client = mock_httpx

    await client.close()
    mock_httpx.aclose.assert_not_called()

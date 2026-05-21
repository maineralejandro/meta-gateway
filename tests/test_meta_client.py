from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.meta_client import MetaAPIClient


@pytest.fixture
def client():
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v18.0/123456"
    c._client = None
    c._cached_token = None
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
    with patch.object(client, "check_token_health", new_callable=AsyncMock) as mock_th:
        mock_th.return_value = {"valid": True, "type": "SYSTEM_USER", "expires_at": 0, "scopes": []}
        result = await client.health_check()

    assert result["connected"] is True
    assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_health_check_no_token(client):
    with patch.object(client, "check_token_health", new_callable=AsyncMock) as mock_th:
        mock_th.return_value = {"valid": False, "error": "No WHATSAPP_ACCESS_TOKEN found"}
        result = await client.health_check()

    assert result["connected"] is False
    assert "No WHATSAPP_ACCESS_TOKEN" in result["error"]


@pytest.mark.asyncio
async def test_health_check_exception(client):
    with patch.object(client, "check_token_health", new_callable=AsyncMock) as mock_th:
        mock_th.side_effect = ConnectionError("DNS failed")
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


@pytest.mark.asyncio
async def test_mark_read_success(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True}
    mock_httpx.post.return_value = mock_resp

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.mark_read("wamid.HBgLMTY1")

    mock_httpx.post.assert_called_once()
    call_args = mock_httpx.post.call_args
    assert call_args[0][0].endswith("/messages")
    payload = call_args[1]["json"]
    assert payload["messaging_product"] == "whatsapp"
    assert payload["status"] == "read"
    assert payload["message_id"] == "wamid.HBgLMTY1"
    assert "typing_indicator" not in payload
    assert result["success"] is True


@pytest.mark.asyncio
async def test_mark_read_with_typing_success(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True}
    mock_httpx.post.return_value = mock_resp

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.mark_read_with_typing("wamid.HBgLMTY1")

    mock_httpx.post.assert_called_once()
    call_args = mock_httpx.post.call_args
    assert call_args[0][0].endswith("/messages")
    payload = call_args[1]["json"]
    assert payload["messaging_product"] == "whatsapp"
    assert payload["status"] == "read"
    assert payload["message_id"] == "wamid.HBgLMTY1"
    assert payload["typing_indicator"] == {"type": "text"}
    assert result["success"] is True


@pytest.mark.asyncio
async def test_mark_read_http_error(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    mock_httpx.post.return_value = mock_resp

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.mark_read("wamid.HBgLMTY1")

    assert result["error"] is True
    assert result["status"] == 401


@pytest.mark.asyncio
async def test_token_auto_refresh():
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v18.0/123456"
    c._client = None
    c._cached_token = None

    with patch.object(c, "_resolve_token", return_value="token-v1"):
        await c._get_client()
        assert c._cached_token == "token-v1"

    with patch.object(c, "_resolve_token", return_value="token-v2"):
        old_client = c._client
        client2 = await c._get_client()
        assert c._cached_token == "token-v2"
        assert client2 is not old_client
        assert old_client.is_closed


@pytest.mark.asyncio
async def test_token_unchanged_reuses_client():
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v18.0/123456"
    c._client = None
    c._cached_token = None

    with patch.object(c, "_resolve_token", return_value="same-token"):
        client1 = await c._get_client()
        client2 = await c._get_client()
        assert client1 is client2


def test_resolve_token_fallback():
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v18.0/123456"

    with patch.dict("os.environ", {}, clear=True), \
         patch("core.meta_client.dotenv_values", side_effect=OSError("no file")), \
         patch("core.meta_client.settings") as mock_settings:
        mock_settings.WHATSAPP_ACCESS_TOKEN = "fallback-token"
        token = c._resolve_token()
        assert token == "fallback-token"


def test_resolve_token_from_env():
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v18.0/123456"

    with patch.dict("os.environ", {}, clear=True), \
         patch("core.meta_client.dotenv_values", return_value={"WHATSAPP_ACCESS_TOKEN": "fresh-token"}):
        token = c._resolve_token()
        assert token == "fresh-token"


def test_resolve_token_empty_env_falls_back():
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v18.0/123456"

    with patch.dict("os.environ", {}, clear=True), \
         patch("core.meta_client.dotenv_values", return_value={"WHATSAPP_ACCESS_TOKEN": ""}), \
         patch("core.meta_client.settings") as mock_settings:
        mock_settings.WHATSAPP_ACCESS_TOKEN = "settings-token"
        token = c._resolve_token()
        assert token == "settings-token"


def test_resolve_token_os_environ_over_dotenv():
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v18.0/123456"

    with patch.dict("os.environ", {"WHATSAPP_ACCESS_TOKEN": "env-var-token"}, clear=True), \
         patch("core.meta_client.dotenv_values", return_value={"WHATSAPP_ACCESS_TOKEN": ""}), \
         patch("core.meta_client.settings") as mock_settings:
        mock_settings.WHATSAPP_ACCESS_TOKEN = "settings-token"
        token = c._resolve_token()
        assert token == "env-var-token"


def test_resolve_token_dotenv_over_os_environ():
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v18.0/123456"

    with patch.dict("os.environ", {"WHATSAPP_ACCESS_TOKEN": "env-var-token"}, clear=True), \
         patch("core.meta_client.dotenv_values", return_value={"WHATSAPP_ACCESS_TOKEN": "dotenv-token"}), \
         patch("core.meta_client.settings") as mock_settings:
        mock_settings.WHATSAPP_ACCESS_TOKEN = "settings-token"
        token = c._resolve_token()
        assert token == "dotenv-token"


@pytest.mark.asyncio
async def test_send_interactive_buttons_success(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid_btn"}]}
    mock_httpx.post.return_value = mock_resp

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.send_interactive_buttons(
            "56912345678",
            "Desea agregar al carrito?",
            [{"id": "yes", "title": "Sí"}, {"id": "no", "title": "No"}],
        )

    assert "error" not in result
    call_args = mock_httpx.post.call_args
    payload = call_args[1]["json"]
    assert payload["type"] == "interactive"
    assert payload["interactive"]["type"] == "button"
    assert len(payload["interactive"]["action"]["buttons"]) == 2


@pytest.mark.asyncio
async def test_send_interactive_buttons_truncated_to_3(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid_btn"}]}
    mock_httpx.post.return_value = mock_resp

    buttons = [{"id": f"b{i}", "title": f"Button {i}"} for i in range(5)]

    with patch.object(client, "_get_client", return_value=mock_httpx):
        await client.send_interactive_buttons("56912345678", "Choose", buttons)

    call_args = mock_httpx.post.call_args
    payload = call_args[1]["json"]
    assert len(payload["interactive"]["action"]["buttons"]) == 3


@pytest.mark.asyncio
async def test_send_interactive_list_success(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid_list"}]}
    mock_httpx.post.return_value = mock_resp

    sections = [{
        "title": "Frutas",
        "rows": [{"id": "frutilla", "title": "Frutilla"}, {"id": "manzana", "title": "Manzana"}],
    }]

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.send_interactive_list(
            "56912345678", "Elige un producto", "Ver productos", sections,
        )

    assert "error" not in result
    call_args = mock_httpx.post.call_args
    payload = call_args[1]["json"]
    assert payload["type"] == "interactive"
    assert payload["interactive"]["type"] == "list"


@pytest.mark.asyncio
async def test_check_token_health_with_app_access_token(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "is_valid": True,
            "type": "SYSTEM_USER",
            "expires_at": 0,
            "scopes": ["whatsapp_business_messaging"],
        }
    }

    mock_cm = AsyncMock()
    mock_cm.get.return_value = mock_resp
    mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("core.meta_client.settings") as mock_settings, \
         patch.object(client, "_resolve_token", return_value="sys-user-token"), \
         patch("httpx.AsyncClient", return_value=mock_cm):
        mock_settings.META_APP_ID = "12345"
        mock_settings.META_APP_SECRET = "abcde"
        mock_settings.META_API_URL = "https://graph.facebook.com/v25.0"
        result = await client.check_token_health()

    assert result["valid"] is True
    assert result["type"] == "SYSTEM_USER"


@pytest.mark.asyncio
async def test_check_token_health_fallback_permissions(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {"permission": "whatsapp_business_messaging", "status": "active"},
        ]
    }

    mock_cm = AsyncMock()
    mock_cm.get.return_value = mock_resp
    mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("core.meta_client.settings") as mock_settings, \
         patch.object(client, "_resolve_token", return_value="sys-user-token"), \
         patch("httpx.AsyncClient", return_value=mock_cm):
        mock_settings.META_APP_ID = ""
        mock_settings.META_APP_SECRET = "abcde"
        mock_settings.META_API_URL = "https://graph.facebook.com/v25.0"
        result = await client.check_token_health()

    assert result["valid"] is True
    assert result["type"] == "SYSTEM_USER"
    assert result["expires_at"] == 0


@pytest.mark.asyncio
async def test_health_check_uses_token_health(client):
    with patch.object(client, "check_token_health", new_callable=AsyncMock) as mock_th:
        mock_th.return_value = {"valid": True, "type": "SYSTEM_USER", "expires_at": 0, "scopes": []}
        result = await client.health_check()

        assert result["connected"] is True
        assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_send_image_success(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid_img"}]}
    mock_httpx.post.return_value = mock_resp

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.send_image("56912345678", "https://example.com/product.jpg", caption="Producto X")

    assert "error" not in result
    call_args = mock_httpx.post.call_args
    payload = call_args[1]["json"]
    assert payload["type"] == "image"
    assert payload["image"]["url"] == "https://example.com/product.jpg"
    assert payload["image"]["caption"] == "Producto X"


@pytest.mark.asyncio
async def test_send_image_without_caption(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid_img"}]}
    mock_httpx.post.return_value = mock_resp

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.send_image("56912345678", "https://example.com/img.jpg")

    assert "error" not in result
    call_args = mock_httpx.post.call_args
    payload = call_args[1]["json"]
    assert "caption" not in payload["image"]


@pytest.mark.asyncio
async def test_send_image_http_error(client):
    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    mock_httpx.post.return_value = mock_resp

    with patch.object(client, "_get_client", return_value=mock_httpx):
        result = await client.send_image("56912345678", "https://example.com/img.jpg")

    assert result["error"] is True
    assert result["status"] == 401

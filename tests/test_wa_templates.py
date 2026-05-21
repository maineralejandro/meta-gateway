from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import WhatsAppTemplate


@pytest.fixture
def sample_template():
    return WhatsAppTemplate(
        id=1,
        agent_id=1,
        template_name="greeting",
        template_type="UTILITY",
        category="UTILITY",
        language="es",
        status="APPROVED",
        body_text="Hola {{1}}, gracias por contactarnos.",
        header_text=None,
        header_image_url=None,
        footer_text=None,
        buttons_json="[]",
        meta_template_id="meta_123",
        meta_quality_rating="GREEN",
        rejection_reason=None,
        created_at="2026-05-20T12:00:00Z",
        updated_at="2026-05-20T12:00:00Z",
    )


@pytest.mark.asyncio
async def test_send_template_success():
    from core.meta_client import MetaAPIClient
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v25.0/123456"
    c._client = None
    c._cached_token = None

    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid_tpl"}]}
    mock_httpx.post.return_value = mock_resp

    with patch.object(c, "_get_client", return_value=mock_httpx):
        result = await c.send_template("56912345678", "greeting", language="es")

    assert "error" not in result
    call_args = mock_httpx.post.call_args
    payload = call_args[1]["json"]
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "greeting"
    assert payload["template"]["language"]["code"] == "es"


@pytest.mark.asyncio
async def test_send_template_with_components():
    from core.meta_client import MetaAPIClient
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v25.0/123456"
    c._client = None
    c._cached_token = None

    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "wamid_tpl2"}]}
    mock_httpx.post.return_value = mock_resp

    components = [{"type": "body", "parameters": [{"type": "text", "text": "Juan"}]}]

    with patch.object(c, "_get_client", return_value=mock_httpx):
        await c.send_template("56912345678", "greeting", components=components)

    call_args = mock_httpx.post.call_args
    payload = call_args[1]["json"]
    assert payload["template"]["components"] == components


@pytest.mark.asyncio
async def test_send_template_http_error():
    from core.meta_client import MetaAPIClient
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v25.0/123456"
    c._client = None
    c._cached_token = None

    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    mock_httpx.post.return_value = mock_resp

    with patch.object(c, "_get_client", return_value=mock_httpx):
        result = await c.send_template("56912345678", "greeting")

    assert result["error"] is True
    assert result["status"] == 401


@pytest.mark.asyncio
async def test_get_templates_pagination():
    from core.meta_client import MetaAPIClient
    c = MetaAPIClient.__new__(MetaAPIClient)
    c.base_url = "https://graph.facebook.com/v25.0/123456"
    c._client = None
    c._cached_token = None

    page1_resp = MagicMock()
    page1_resp.status_code = 200
    page1_resp.json.return_value = {
        "data": [{"id": "1", "name": "greeting"}],
        "paging": {},
    }

    mock_httpx = AsyncMock()
    mock_httpx.get.return_value = page1_resp

    with patch.object(c, "_get_client", return_value=mock_httpx):
        result = await c.get_templates("waba_123")

    assert len(result) == 1
    assert result[0]["name"] == "greeting"


@pytest.mark.asyncio
async def test_can_send_free_form_within_24h():
    from datetime import UTC, datetime, timedelta

    from core.hitl_router import _can_send_free_form

    mock_conv = MagicMock()
    mock_conv.last_message_at = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()

    mock_db = MagicMock()
    mock_db.get_conversation = AsyncMock(return_value=mock_conv)

    result = await _can_send_free_form("56912345678", mock_db)
    assert result is True


@pytest.mark.asyncio
async def test_can_send_free_form_outside_24h():
    from datetime import UTC, datetime, timedelta

    from core.hitl_router import _can_send_free_form

    mock_conv = MagicMock()
    mock_conv.last_message_at = (datetime.now(tz=UTC) - timedelta(hours=25)).isoformat()

    mock_db = MagicMock()
    mock_db.get_conversation = AsyncMock(return_value=mock_conv)

    result = await _can_send_free_form("56912345678", mock_db)
    assert result is False


@pytest.mark.asyncio
async def test_can_send_free_form_no_conversation():
    from core.hitl_router import _can_send_free_form

    mock_db = MagicMock()
    mock_db.get_conversation = AsyncMock(return_value=None)

    result = await _can_send_free_form("56912345678", mock_db)
    assert result is False


@pytest.mark.asyncio
async def test_select_template_for_reply_keywords():
    from core.hitl_router import _select_template_for_reply

    mock_template = WhatsAppTemplate(
        id=1, template_name="order_confirmation", status="APPROVED",
        body_text="Pedido confirmado",
    )
    mock_db = MagicMock()
    mock_db.whatsapp_templates = MagicMock()
    mock_db.whatsapp_templates.get_by_name = AsyncMock(return_value=mock_template)

    result = await _select_template_for_reply("Tu pedido ha sido confirmado. Total: $5000", mock_db)
    assert result is not None
    assert result["name"] == "order_confirmation"


@pytest.mark.asyncio
async def test_select_template_for_reply_fallback_greeting():
    from core.hitl_router import _select_template_for_reply

    mock_greeting = WhatsAppTemplate(
        id=2, template_name="greeting", status="APPROVED",
        body_text="Hola",
    )
    mock_db = MagicMock()
    mock_db.whatsapp_templates = MagicMock()
    mock_db.whatsapp_templates.get_by_name = AsyncMock(return_value=None)
    mock_db.whatsapp_templates.get_all = AsyncMock(return_value=[mock_greeting])

    result = await _select_template_for_reply("Mensaje genérico", mock_db)
    assert result is not None
    assert result["name"] == "greeting"


@pytest.mark.asyncio
async def test_select_template_no_approved():
    from core.hitl_router import _select_template_for_reply

    mock_db = MagicMock()
    mock_db.whatsapp_templates = MagicMock()
    mock_db.whatsapp_templates.get_by_name = AsyncMock(return_value=None)
    mock_db.whatsapp_templates.get_all = AsyncMock(return_value=[])

    result = await _select_template_for_reply("Mensaje genérico", mock_db)
    assert result is None

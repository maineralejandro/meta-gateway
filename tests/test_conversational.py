import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from core.capabilities.base import registry as capability_registry
from core.capabilities.cart import CartCapability
from core.capabilities.cart import CartCapability as CartState
from core.container import container
from core.memory import WINDOW_SIZE, memory_manager
from core.sentiment import SentimentAnalyzer
from db.database import db
from routers.webhook import receive_webhook

cart_state = getattr(container, 'cart_capability', None) or CartState()

_CATALOG_SEED = [
    ("item_a", "Item A Special", 3700, "general"),
    ("item_b", "Item B Classic", 2400, "general"),
    ("item_c", "Item C Special", 3400, "general"),
    ("item_d", "Item D Premium", 8900, "general"),
    ("item_e", "Item E Classic", 3700, "general"),
    ("item_f", "Item F Budget", 1500, "general"),
]


@pytest_asyncio.fixture(autouse=True)
async def _reset_cart_and_registry():
    cart_state._carts.clear()
    cart_state._loaded_phones.clear()
    if not capability_registry.get_class("cart"):
        capability_registry.register(CartCapability)

    await db.executemany(
        "INSERT INTO catalog_items (key, name, price, category, is_available, sort_order, description, tags, size, specifications) "
        "VALUES ($1, $2, $3, $4, TRUE, 0, '', '[]', '', '')",
        [(k, n, p, c) for k, n, p, c in _CATALOG_SEED],
    )
    await cart_state.reload_catalog_from_db()

    yield


@dataclass
class TurnResult:
    sent_text: str | None
    escalated: bool
    cart: dict
    conv_state: str
    decision: dict | None
    ws_messages: list[dict]


async def turn(
    phone: str,
    text: str,
    *,
    llm_response: str = "OK",
    llm_escalate: bool = False,
    sentiment_result: dict | None = None,
) -> TurnResult:
    sent_texts = []
    emitted_events = []

    async def capture_send_text(p, t):
        sent_texts.append(t)

    async def capture_emit(event_type, payload):
        emitted_events.append({"type": event_type, **payload})

    with patch(
        "core.hitl_router.inference_engine"
    ) as mock_engine, patch(
        "core.hitl_router.meta_client"
    ) as mock_meta, patch(
        "core.hitl_router.emit", new=AsyncMock()
    ) as mock_emit, patch(
        "core.hitl_router.sentiment_analyzer"
    ) as mock_sentiment, patch(
        "core.hitl_router.track_task"
    ), patch(
        "core.hitl_router._safe_summarize", new=AsyncMock()
    ), patch(
        "core.hitl_router.capability_registry"
    ) as mock_registry:
        mock_engine.generate = AsyncMock(return_value=(llm_response, llm_escalate, {"source": "llm"}))
        mock_engine._current_agent = None
        mock_meta.send_text = capture_send_text
        mock_emit.side_effect = capture_emit
        mock_registry.resolve = AsyncMock(return_value=[cart_state])

        if sentiment_result is not None:
            mock_sentiment.analyze = AsyncMock(return_value=sentiment_result)
        else:
            analyzer = SentimentAnalyzer()
            analyzer.client = None
            analyzer._available = False
            mock_sentiment.analyze = analyzer.analyze

        from core.hitl_router import hitl_router
        await hitl_router.process_inbound_message(phone, text)

    conv = await db.get_conversation(phone)
    cart = await cart_state.get_cart(phone)

    decision_row = await db.fetchone(
        "SELECT * FROM agent_decisions WHERE phone=$1 ORDER BY created_at DESC LIMIT 1",
        phone,
    )

    return TurnResult(
        sent_text=sent_texts[0] if sent_texts else None,
        escalated=any(e.get("type") == "escalated" for e in emitted_events),
        cart=cart,
        conv_state=conv.state if conv else "BOT_ACTIVE",
        decision=dict(decision_row) if decision_row else None,
        ws_messages=emitted_events,
    )


async def _ensure_conversation(phone: str, state: str = "BOT_ACTIVE", agent_id: int = 1):
    existing = await db.get_conversation(phone)
    if not existing:
        await db.execute(
            "INSERT INTO conversations (phone, state, agent_id) VALUES ($1, $2, $3)",
            phone, state, agent_id,
        )


@pytest.mark.asyncio
async def test_simple_cart_accumulation():
    phone = "+56910000001"
    await _ensure_conversation(phone)

    await cart_state.add_item(phone, "item_c", 3)
    cart = await cart_state.get_cart(phone)
    assert len(cart["items"]) == 1
    assert cart["items"][0]["key"] == "item_c"
    assert cart["items"][0]["quantity"] == 3
    assert cart["total"] == 3400 * 3

    await cart_state.add_item(phone, "item_e", 2)
    cart = await cart_state.get_cart(phone)
    assert len(cart["items"]) == 2
    assert cart["total"] == 3400 * 3 + 3700 * 2


@pytest.mark.asyncio
async def test_cart_remove_partial():
    phone = "+56910000002"
    await _ensure_conversation(phone)
    await cart_state.add_item(phone, "item_a", 4)

    await cart_state.remove_item(phone, "item_a", 1)
    cart = await cart_state.get_cart(phone)
    item = next(i for i in cart["items"] if i["key"] == "item_a")
    assert item["quantity"] == 3
    assert cart["total"] == 3700 * 3


@pytest.mark.asyncio
async def test_cart_remove_all_quantity():
    phone = "+56910000003"
    await _ensure_conversation(phone)
    await cart_state.add_item(phone, "item_f", 2)
    await cart_state.add_item(phone, "item_a", 1)

    await cart_state.remove_item(phone, "item_f", 2)
    cart = await cart_state.get_cart(phone)
    keys = [i["key"] for i in cart["items"]]
    assert "item_f" not in keys
    assert "item_a" in keys
    assert cart["total"] == 3700


@pytest.mark.asyncio
async def test_cart_clear():
    phone = "+56910000004"
    await _ensure_conversation(phone)
    await cart_state.add_item(phone, "item_c", 3)
    await cart_state.add_item(phone, "item_e", 2)

    await cart_state.clear(phone)
    cart = await cart_state.get_cart(phone)
    assert cart["items"] == []
    assert cart["total"] == 0
    result = await cart_state.format_for_context(phone)
    assert result is not None
    assert "Catalogo disponible" in result


@pytest.mark.asyncio
async def test_unknown_item_key_ignored():
    phone = "+56910000006"
    await _ensure_conversation(phone)

    await cart_state.add_item(phone, "pizza_hawaiana", 1)
    cart = await cart_state.get_cart(phone)
    assert cart["items"] == []
    assert cart["total"] == 0


@pytest.mark.asyncio
async def test_escalation_keyword_triggers_human():
    phone = "+56910000007"
    await _ensure_conversation(phone)

    r = await turn(
        phone,
        "quiero cancelar todo",
        llm_response="Entendido",
    )
    assert r.escalated is True
    assert r.conv_state == "PENDING_APPROVAL"
    assert r.decision["escalate_reason"] is not None


@pytest.mark.asyncio
async def test_negative_caps_exclamation_escalation():
    phone = "+56910000008"
    await _ensure_conversation(phone)

    r = await turn(
        phone,
        "PESIMO HORRIBLE!!!",
        llm_response="Disculpe",
    )
    assert r.escalated is True
    assert r.conv_state == "PENDING_APPROVAL"


@pytest.mark.asyncio
async def test_llm_escalate_marker():
    phone = "+56910000009"
    await _ensure_conversation(phone)

    r = await turn(
        phone,
        "no entiendo",
        llm_response="Un momento, te comunico con un atendedor.",
        llm_escalate=True,
    )
    assert r.escalated is True
    assert r.decision["llm_escalate"] == 1


@pytest.mark.asyncio
async def test_no_escalation_normal_question():
    phone = "+56910000010"
    await _ensure_conversation(phone)

    r = await turn(
        phone,
        "hola, cuanto cuesta el completo?",
        llm_response="El completo cuesta $3.700",
    )
    assert r.escalated is False
    assert r.conv_state == "BOT_ACTIVE"


@pytest.mark.asyncio
async def test_escalation_skips_order_operations():
    phone = "+56910000011"
    await _ensure_conversation(phone)

    r = await turn(
        phone,
        "estoy molesto, pero quiero un completo",
        llm_response="Entendido",
        llm_escalate=True,
    )
    assert r.escalated is True
    assert r.cart["items"] == []


@pytest.mark.asyncio
async def test_confidence_below_04_escalates():
    phone = "+56910000012"
    await _ensure_conversation(phone)

    r = await turn(
        phone,
        "algo ambiguo",
        llm_response="No estoy seguro",
        sentiment_result={
            "sentiment": "neutral",
            "score": 0.5,
            "confidence": 0.35,
        },
    )
    assert r.escalated is True
    assert "very_low_confidence" in (r.decision.get("escalate_reason") or "")


@pytest.mark.asyncio
async def test_confidence_045_no_escalation():
    phone = "+56910000013"
    await _ensure_conversation(phone)

    r = await turn(
        phone,
        "una pregunta normal",
        llm_response="Aqui va la respuesta",
        sentiment_result={
            "sentiment": "neutral",
            "score": 0.6,
            "confidence": 0.45,
        },
    )
    assert r.escalated is False
    assert r.conv_state == "BOT_ACTIVE"


@pytest.mark.asyncio
async def test_message_dedup_in_context():
    phone = "+56910000014"
    await _ensure_conversation(phone)

    await db.execute(
        "INSERT INTO messages (phone, direction, source, text) VALUES ($1, 'inbound', 'customer', 'Hola')",
        phone,
    )
    await db.execute(
        "INSERT INTO messages (phone, direction, source, text) VALUES ($1, 'outbound', 'bot', 'Bienvenido')",
        phone,
    )
    await db.execute(
        "INSERT INTO messages (phone, direction, source, text) VALUES ($1, 'inbound', 'customer', 'Quiero item')",
        phone,
    )

    context = await memory_manager.build_context(phone, current_message="Quiero item", agent_id=1)
    texts = [c["content"] for c in context]
    inbound_count = sum(1 for t in texts if t == "Quiero item")
    assert inbound_count == 0


@pytest.mark.asyncio
async def test_window_newest_not_oldest():
    phone = "+56910000015"
    await _ensure_conversation(phone)

    for i in range(30):
        await db.execute(
            "INSERT INTO turns (phone, user_text, assistant_text) VALUES ($1, $2, $3)",
            phone, f"Mensaje {i}", f"Respuesta {i}",
        )

    context = await memory_manager.build_context(phone, agent_id=1)
    turn_messages = [c for c in context if c["role"] in ("user", "assistant")]
    assert len(turn_messages) == WINDOW_SIZE * 2
    texts = [c["content"] for c in turn_messages if c["role"] == "user"]
    assert "Mensaje 14" in texts
    assert "Mensaje 29" in texts
    assert "Mensaje 0" not in texts
    assert "Mensaje 13" not in texts


@pytest.mark.asyncio
async def test_cart_state_format_injects_order():
    phone = "+56910000016"
    await _ensure_conversation(phone)

    ctx = await cart_state.format_for_context(phone, {})
    assert ctx is not None

    await cart_state.add_item(phone, "item_c", 3)
    await cart_state.add_item(phone, "item_e", 2)

    ctx = await cart_state.format_for_context(phone, {})
    assert "Item C Special" in ctx
    assert "$" in ctx


@pytest.mark.asyncio
async def test_multiple_phones_independent_orders():
    phone_a = "+56910000017"
    phone_b = "+56910000018"
    await _ensure_conversation(phone_a)
    await _ensure_conversation(phone_b)

    await cart_state.add_item(phone_a, "item_a", 2)
    await cart_state.add_item(phone_b, "item_d", 1)

    cart_a = await cart_state.get_cart(phone_a)
    cart_b = await cart_state.get_cart(phone_b)

    assert len(cart_a["items"]) == 1
    assert cart_a["items"][0]["key"] == "item_a"
    assert cart_a["total"] == 3700 * 2

    assert len(cart_b["items"]) == 1
    assert cart_b["items"][0]["key"] == "item_d"
    assert cart_b["total"] == 8900


@pytest.mark.asyncio
async def test_sanitize_in_output():
    phone = "+56910000019"
    await _ensure_conversation(phone)

    dirty_response = "Pedido listo!\x00" + "X" * 2100
    r = await turn(
        phone,
        "confirmar",
        llm_response=dirty_response,
    )
    assert "\x00" not in r.sent_text
    assert len(r.sent_text) <= 2000


@pytest.mark.asyncio
async def test_error_handling_does_not_crash():
    phone = "+56910000020"
    await _ensure_conversation(phone)

    ws_messages = []

    async def capture_emit(event_type, payload):
        ws_messages.append({"type": event_type, **payload})

    with patch(
        "core.hitl_router.inference_engine"
    ) as mock_engine, patch(
        "core.hitl_router.meta_client"
    ) as mock_meta, patch(
        "core.hitl_router.emit", new=AsyncMock()
    ) as mock_emit, patch(
        "core.hitl_router.sentiment_analyzer"
    ) as mock_sentiment, patch(
        "core.hitl_router.track_task"
    ), patch(
        "core.hitl_router._safe_summarize", new=AsyncMock()
    ), patch(
        "core.hitl_router.capability_registry"
    ) as mock_registry:

        mock_sentiment.analyze = AsyncMock(return_value={
            "sentiment": "neutral", "score": 0.5, "confidence": 0.8
        })
        mock_engine.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
        mock_engine._current_agent = None
        mock_meta.send_text = AsyncMock()
        mock_emit.side_effect = capture_emit
        mock_registry.resolve = AsyncMock(return_value=[cart_state])

        from core.hitl_router import hitl_router
        await hitl_router.process_inbound_message(phone, "algo")

    error_msgs = [m for m in ws_messages if m.get("type") == "error"]
    assert len(error_msgs) == 1
    assert "LLM down" in error_msgs[0]["error"]


@pytest.mark.asyncio
async def test_human_only_skips_processing():
    phone = "+56910000021"
    await db.execute(
        "INSERT INTO conversations (phone, state, agent_id, requires_human_review) VALUES ($1, 'HUMAN_ONLY', 1, TRUE)",
        phone,
    )

    body = json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "messages": [{"from": phone, "id": "m1", "text": {"body": "Hola"}, "type": "text"}]
        }}]}]
    }).encode()
    sig = "sha256=" + hmac.new(b"test_secret", body, hashlib.sha256).hexdigest()

    with patch("routers.webhook.turn_builder") as mock_tb, \
         patch("routers.webhook.meta_client") as mock_meta, \
         patch("routers.webhook.verify_meta_signature", return_value=True):
        mock_tb.debounce = AsyncMock()
        mock_meta.mark_read = AsyncMock()
        mock_meta.mark_read_with_typing = AsyncMock()
        request = MagicMock()
        request.body = AsyncMock(return_value=body)
        request.headers = {"X-Hub-Signature-256": sig}

        result = await receive_webhook(request)

        if hasattr(result, "status_code"):
            pytest.fail(f"Got HTTP {result.status_code} instead of JSON response")
        assert result["status"] == "pending_human"
        mock_tb.debounce.assert_not_called()


@pytest.mark.asyncio
async def test_pending_approval_queueing():
    phone = "+56910000022"
    await db.execute(
        "INSERT INTO conversations (phone, state, agent_id, requires_human_review) VALUES ($1, 'PENDING_APPROVAL', 1, FALSE)",
        phone,
    )

    body = json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "messages": [{"from": phone, "id": "m2", "text": {"body": "Hola"}, "type": "text"}]
        }}]}]
    }).encode()
    sig = "sha256=" + hmac.new(b"test_secret", body, hashlib.sha256).hexdigest()

    with patch("routers.webhook.turn_builder") as mock_tb, \
         patch("routers.webhook.meta_client") as mock_meta, \
         patch("routers.webhook.verify_meta_signature", return_value=True):
        mock_tb.debounce = AsyncMock()
        mock_meta.mark_read = AsyncMock()
        mock_meta.mark_read_with_typing = AsyncMock()
        request = MagicMock()
        request.body = AsyncMock(return_value=body)
        request.headers = {"X-Hub-Signature-256": sig}

        result = await receive_webhook(request)

        if hasattr(result, "status_code"):
            pytest.fail(f"Got HTTP {result.status_code} instead of JSON response")
        assert result["status"] == "pending_approval"
        mock_tb.debounce.assert_not_called()


@pytest.mark.asyncio
async def test_regression_original_incident():
    phone = "+56919999999"
    await _ensure_conversation(phone)

    await cart_state.add_item(phone, "item_c", 3)
    cart = await cart_state.get_cart(phone)
    assert len(cart["items"]) == 1
    assert cart["items"][0]["key"] == "item_c"
    assert cart["items"][0]["quantity"] == 3
    assert cart["items"][0]["price"] == 3400
    assert cart["total"] == 3400 * 3

    await cart_state.add_item(phone, "item_e", 2)
    cart = await cart_state.get_cart(phone)
    assert len(cart["items"]) == 2
    assert cart["total"] == 3400 * 3 + 3700 * 2

    await cart_state.add_item(phone, "item_f", 1)
    cart = await cart_state.get_cart(phone)
    assert len(cart["items"]) == 3
    assert cart["total"] == 3400 * 3 + 3700 * 2 + 1500

    all_keys = [i["key"] for i in cart["items"]]
    assert "item_c" in all_keys
    assert "item_e" in all_keys
    assert "item_f" in all_keys
    assert "item_b" not in all_keys
    assert len(cart["items"]) == 3

    conv = await db.get_conversation(phone)
    assert conv.state == "BOT_ACTIVE"


@pytest.mark.asyncio
async def test_webhook_duplicate_message_ignored():
    phone = "+56910000023"
    await _ensure_conversation(phone)

    body = json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "messages": [{"from": phone, "id": "wamid_dup_test_001", "text": {"body": "Hola"}, "type": "text"}]
        }}]}]
    }).encode()
    sig = "sha256=" + hmac.new(b"test_secret", body, hashlib.sha256).hexdigest()

    request = MagicMock()
    request.body = AsyncMock(return_value=body)
    request.headers = {"X-Hub-Signature-256": sig}

    with patch("routers.webhook.turn_builder") as mock_tb, \
         patch("routers.webhook.meta_client") as mock_meta, \
         patch("routers.webhook.settings") as mock_settings, \
         patch("routers.webhook.verify_meta_signature", return_value=True):
        mock_tb.debounce = AsyncMock()
        mock_meta.mark_read = AsyncMock()
        mock_meta.mark_read_with_typing = AsyncMock()
        mock_settings.MARK_READ_DELAY_MS = 0
        result1 = await receive_webhook(request)
        assert result1["status"] == "processing"
        await asyncio.sleep(0)
        assert mock_tb.debounce.call_count == 1

    with patch("routers.webhook.turn_builder") as mock_tb, \
         patch("routers.webhook.meta_client") as mock_meta, \
         patch("routers.webhook.settings") as mock_settings, \
         patch("routers.webhook.verify_meta_signature", return_value=True):
        mock_tb.debounce = AsyncMock()
        mock_meta.mark_read = AsyncMock()
        mock_meta.mark_read_with_typing = AsyncMock()
        mock_settings.MARK_READ_DELAY_MS = 0
        result2 = await receive_webhook(request)
        assert result2["status"] == "duplicate"
        mock_tb.debounce.assert_not_called()


@pytest.mark.asyncio
async def test_should_escalate_keyword_beats_tools_ok():
    from core.hitl_router import HITLRouter

    router = HITLRouter()
    trace = {"tools_executed": json.dumps([{"tool": "cart_clear", "result": {"success": True}}])}
    escalate, reason = await router.should_escalate(
        sentiment_result={"sentiment": "neutral", "score": 0.5, "confidence": 0.8},
        text="estoy molesto",
        llm_escalate=False,
        trace=trace,
    )
    assert escalate is True
    assert "escalation_keyword" in reason


@pytest.mark.asyncio
async def test_should_escalate_negative_sentiment_beats_tools_ok():
    from core.hitl_router import HITLRouter

    router = HITLRouter()
    trace = {"tools_executed": json.dumps([{"tool": "cart_add", "result": {"success": True}}])}
    escalate, reason = await router.should_escalate(
        sentiment_result={"sentiment": "negative", "score": 0.2, "confidence": 0.8},
        text="producto malo",
        llm_escalate=False,
        trace=trace,
    )
    assert escalate is True
    assert "negative_sentiment" in reason


@pytest.mark.asyncio
async def test_should_escalate_tools_ok_blocks_low_confidence():
    from core.hitl_router import HITLRouter

    router = HITLRouter()
    trace = {"tools_executed": json.dumps([{"tool": "cart_add", "result": {"success": True}}])}
    escalate, _reason = await router.should_escalate(
        sentiment_result={"sentiment": "neutral", "score": 0.5, "confidence": 0.3},
        text="algo ambiguo",
        llm_escalate=False,
        trace=trace,
    )
    assert escalate is False


@pytest.mark.asyncio
async def test_should_escalate_low_confidence_without_tools():
    from core.hitl_router import HITLRouter

    router = HITLRouter()
    escalate, reason = await router.should_escalate(
        sentiment_result={"sentiment": "neutral", "score": 0.5, "confidence": 0.3},
        text="algo ambiguo",
        llm_escalate=False,
        trace=None,
    )
    assert escalate is True
    assert "very_low_confidence" in reason

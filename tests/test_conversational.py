import pytest
import pytest_asyncio
import os
import json
import asyncio
import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from dataclasses import dataclass

from core.config import settings
from core.order_state import order_state, OrderState, MENU_ITEMS
from core.memory import memory_manager, WINDOW_SIZE
from core.sentiment import SentimentAnalyzer
from core.security import sanitize_llm_output
from db.database import db, init_db, close_db, get_db
from routers.webhook import receive_webhook


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_session_db():
    import random
    suffix = random.randint(10000, 99999)
    test_db = f"./tests/data/conversational_{suffix}.db"
    settings.DB_PATH = test_db
    settings.META_APP_SECRET = "test_secret"

    os.makedirs("./tests/data", exist_ok=True)
    if os.path.exists(test_db):
        os.remove(test_db)

    await init_db()
    with open("db/schema.sql", "r") as f:
        schema = f.read()
    conn = await db._get_conn()
    await conn.execute("PRAGMA foreign_keys=OFF")
    await conn.executescript(schema)
    await conn.execute("PRAGMA foreign_keys=ON")
    await db.commit()

    yield
    await close_db()


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    conn = await db._get_conn()
    await conn.execute("PRAGMA foreign_keys=OFF")
    await db.execute("DELETE FROM agent_decisions")
    await db.execute("DELETE FROM escalation_events")
    await db.execute("DELETE FROM messages")
    await db.execute("DELETE FROM conversation_memory")
    await db.execute("DELETE FROM conversations")
    await db.execute("DELETE FROM sessions")
    await db.execute("DELETE FROM agents")
    await db.execute(
        "INSERT INTO agents (id, name, system_prompt, escalation_marker) "
        "VALUES (1, 'Hermes Bot', 'Eres Hermes. Usa tags [ORDER_ADD:key:qty].', 'ESCALATE_TO_HUMAN')"
    )
    await db.commit()
    await conn.execute("PRAGMA foreign_keys=ON")
    order_state._orders.clear()


@dataclass
class TurnResult:
    sent_text: str | None
    escalated: bool
    order: dict
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
    ws_messages = []

    async def capture_send_text(p, t):
        sent_texts.append(t)

    async def capture_ws(msg):
        ws_messages.append(msg)

    with patch(
        "core.hitl_router.inference_engine"
    ) as mock_engine, patch(
        "core.hitl_router.meta_client"
    ) as mock_meta, patch(
        "core.hitl_router.manager"
    ) as mock_ws, patch(
        "core.hitl_router.sentiment_analyzer"
    ) as mock_sentiment, patch(
        "core.hitl_router.asyncio.create_task"
    ) as mock_create_task:

        mock_engine.generate = AsyncMock(return_value=(llm_response, llm_escalate))
        mock_engine._current_agent = None
        mock_meta.send_text = capture_send_text
        mock_ws.send_to_all = capture_ws

        if sentiment_result is not None:
            mock_sentiment.analyze = AsyncMock(return_value=sentiment_result)
        else:
            analyzer = SentimentAnalyzer()
            analyzer.client = None
            analyzer._available = False
            mock_sentiment.analyze = analyzer.analyze

        mock_create_task.side_effect = lambda coro, *a, **kw: coro.close()

        from core.hitl_router import hitl_router
        await hitl_router.process_inbound_message(phone, text)

    conv = await db.get_conversation(phone)
    order = order_state.get_order(phone)

    decision_row = await db.fetchone(
        "SELECT * FROM agent_decisions WHERE phone=? ORDER BY created_at DESC LIMIT 1",
        (phone,),
    )

    return TurnResult(
        sent_text=sent_texts[0] if sent_texts else None,
        escalated=any(m.get("type") == "escalated" for m in ws_messages),
        order=order,
        conv_state=conv.state if conv else "BOT_ACTIVE",
        decision=dict(decision_row) if decision_row else None,
        ws_messages=ws_messages,
    )


async def _ensure_conversation(phone: str, state: str = "BOT_ACTIVE", agent_id: int = 1):
    existing = await db.get_conversation(phone)
    if not existing:
        await db.execute(
            "INSERT INTO conversations (phone, state, agent_id) VALUES (?, ?, ?)",
            (phone, state, agent_id),
        )
        await db.commit()


# ============================================================
# 1-6: ORDER TAG PARSING
# ============================================================


@pytest.mark.asyncio
async def test_simple_order_accumulation():
    phone = "+56910000001"
    await _ensure_conversation(phone)

    r1 = await turn(
        phone,
        "3 vienesas gigantes italianas",
        llm_response="Anotado! [ORDER_ADD:completo_vienesa_gigante:3]",
    )
    assert r1.escalated is False
    assert r1.sent_text == "Anotado!"
    assert len(r1.order["items"]) == 1
    assert r1.order["items"][0]["key"] == "completo_vienesa_gigante"
    assert r1.order["items"][0]["quantity"] == 3
    assert r1.order["total"] == 3400 * 3

    r2 = await turn(
        phone,
        "y 2 papas medianas",
        llm_response="Listo! [ORDER_ADD:papas_mediana:2]",
    )
    assert len(r2.order["items"]) == 2
    assert r2.order["total"] == 3400 * 3 + 3700 * 2
    assert r2.sent_text == "Listo!"


@pytest.mark.asyncio
async def test_order_remove_partial():
    phone = "+56910000002"
    await _ensure_conversation(phone)
    order_state.add_item(phone, "completo_normal", 4)

    r = await turn(
        phone,
        "quita 1 completo",
        llm_response="Quitado [ORDER_REMOVE:completo_normal:1]",
    )
    item = next(i for i in r.order["items"] if i["key"] == "completo_normal")
    assert item["quantity"] == 3
    assert r.order["total"] == 3700 * 3


@pytest.mark.asyncio
async def test_order_remove_all_quantity():
    phone = "+56910000003"
    await _ensure_conversation(phone)
    order_state.add_item(phone, "coca_lata", 2)
    order_state.add_item(phone, "completo_normal", 1)

    r = await turn(
        phone,
        "saca las cocas",
        llm_response="Sacado [ORDER_REMOVE:coca_lata:2]",
    )
    keys = [i["key"] for i in r.order["items"]]
    assert "coca_lata" not in keys
    assert "completo_normal" in keys
    assert r.order["total"] == 3700


@pytest.mark.asyncio
async def test_order_clear():
    phone = "+56910000004"
    await _ensure_conversation(phone)
    order_state.add_item(phone, "completo_vienesa_gigante", 3)
    order_state.add_item(phone, "papas_mediana", 2)

    r = await turn(
        phone,
        "empezar de cero",
        llm_response="Borrado [ORDER_CLEAR]",
    )
    assert r.order["items"] == []
    assert r.order["total"] == 0
    assert order_state.format_for_context(phone) is None


@pytest.mark.asyncio
async def test_tags_stripped_from_user_facing_text():
    phone = "+56910000005"
    await _ensure_conversation(phone)

    r = await turn(
        phone,
        "quiero un completo",
        llm_response="Tu pedido va! [ORDER_ADD:completo_normal:1] gracias",
    )
    assert "[ORDER_ADD" not in r.sent_text
    assert "Tu pedido va!" in r.sent_text
    assert "gracias" in r.sent_text


@pytest.mark.asyncio
async def test_unknown_item_key_ignored():
    phone = "+56910000006"
    await _ensure_conversation(phone)

    r = await turn(
        phone,
        "pizza",
        llm_response="Ahi va [ORDER_ADD:pizza_hawaiana:1]",
    )
    assert r.order["items"] == []
    assert r.order["total"] == 0


# ============================================================
# 7-13: ESCALATION LOGIC
# ============================================================


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
async def test_escalation_skips_order_tag_parsing():
    phone = "+56910000011"
    await _ensure_conversation(phone)

    r = await turn(
        phone,
        "estoy molesto, pero quiero un completo",
        llm_response="Ahi va [ORDER_ADD:completo_normal:1]",
        llm_escalate=True,
    )
    assert r.escalated is True
    assert r.order["items"] == []


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


# ============================================================
# 14-17: CONTEXT BUILDING
# ============================================================


@pytest.mark.asyncio
async def test_message_dedup_in_context():
    phone = "+56910000014"
    await _ensure_conversation(phone)

    await db.execute(
        "INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', 'Hola')",
        (phone,),
    )
    await db.execute(
        "INSERT INTO messages (phone, direction, source, text) VALUES (?, 'outbound', 'bot', 'Bienvenido')",
        (phone,),
    )
    await db.execute(
        "INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', 'Quiero completo')",
        (phone,),
    )
    await db.commit()

    context = await memory_manager.build_context(phone, current_message="Quiero completo")
    texts = [c["content"] for c in context]
    inbound_count = sum(1 for t in texts if t == "Quiero completo")
    assert inbound_count == 0


@pytest.mark.asyncio
async def test_window_newest_not_oldest():
    phone = "+56910000015"
    await _ensure_conversation(phone)

    for i in range(30):
        await db.execute(
            "INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', ?)",
            (phone, f"Mensaje {i}"),
        )
    await db.commit()

    context = await memory_manager.build_context(phone)
    assert len(context) == WINDOW_SIZE
    texts = [c["content"] for c in context]
    assert "Mensaje 14" in texts
    assert "Mensaje 29" in texts
    assert "Mensaje 0" not in texts
    assert "Mensaje 13" not in texts


@pytest.mark.asyncio
async def test_order_state_injected_in_context():
    phone = "+56910000016"
    await _ensure_conversation(phone)

    await db.execute(
        "INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', 'Hola')",
        (phone,),
    )
    await db.commit()

    order_state.add_item(phone, "completo_vienesa_gigante", 3)
    order_state.add_item(phone, "papas_mediana", 2)

    context = await memory_manager.build_context(phone)
    system_msgs = [c for c in context if c["role"] == "system" and "Pedido actual" in c["content"]]
    assert len(system_msgs) == 1
    assert "Vienesa Gigante Italiana" in system_msgs[0]["content"]
    assert "$" in system_msgs[0]["content"]


@pytest.mark.asyncio
async def test_multiple_phones_independent_orders():
    phone_a = "+56910000017"
    phone_b = "+56910000018"
    await _ensure_conversation(phone_a)
    await _ensure_conversation(phone_b)

    order_state.add_item(phone_a, "completo_normal", 2)
    order_state.add_item(phone_b, "chorrillana", 1)

    order_a = order_state.get_order(phone_a)
    order_b = order_state.get_order(phone_b)

    assert len(order_a["items"]) == 1
    assert order_a["items"][0]["key"] == "completo_normal"
    assert order_a["total"] == 3700 * 2

    assert len(order_b["items"]) == 1
    assert order_b["items"][0]["key"] == "chorrillana"
    assert order_b["total"] == 8900


# ============================================================
# 18-21: EDGE CASES
# ============================================================


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

    async def capture_ws(msg):
        ws_messages.append(msg)

    with patch(
        "core.hitl_router.inference_engine"
    ) as mock_engine, patch(
        "core.hitl_router.meta_client"
    ) as mock_meta, patch(
        "core.hitl_router.manager"
    ) as mock_ws, patch(
        "core.hitl_router.sentiment_analyzer"
    ) as mock_sentiment:

        mock_sentiment.analyze = AsyncMock(return_value={
            "sentiment": "neutral", "score": 0.5, "confidence": 0.8
        })
        mock_engine.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
        mock_engine._current_agent = None
        mock_meta.send_text = AsyncMock()
        mock_ws.send_to_all = capture_ws

        from core.hitl_router import hitl_router
        await hitl_router.process_inbound_message(phone, "algo")

    error_msgs = [m for m in ws_messages if m.get("type") == "error"]
    assert len(error_msgs) == 1
    assert "LLM down" in error_msgs[0]["error"]


@pytest.mark.asyncio
async def test_human_only_skips_processing():
    phone = "+56910000021"
    await db.execute(
        "INSERT INTO conversations (phone, state, agent_id, requires_human_review) VALUES (?, 'HUMAN_ONLY', 1, 1)",
        (phone,),
    )
    await db.commit()

    body = json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "messages": [{"from": phone, "id": "m1", "text": {"body": "Hola"}, "type": "text"}]
        }}]}]
    }).encode()
    sig = "sha256=" + hmac.new(b"test_secret", body, hashlib.sha256).hexdigest()

    with patch("routers.webhook.process_inbound_message", new_callable=AsyncMock) as mock_process:
        request = MagicMock()
        request.body = AsyncMock(return_value=body)
        request.headers = {"X-Hub-Signature-256": sig}

        result = await receive_webhook(request)

    if hasattr(result, "status_code"):
        pytest.fail(f"Got HTTP {result.status_code} instead of JSON response")
    assert result["status"] == "pending_human"
    mock_process.assert_not_called()


@pytest.mark.asyncio
async def test_pending_approval_queueing():
    phone = "+56910000022"
    await db.execute(
        "INSERT INTO conversations (phone, state, agent_id, requires_human_review) VALUES (?, 'PENDING_APPROVAL', 1, 0)",
        (phone,),
    )
    await db.commit()

    body = json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "messages": [{"from": phone, "id": "m2", "text": {"body": "Hola"}, "type": "text"}]
        }}]}]
    }).encode()
    sig = "sha256=" + hmac.new(b"test_secret", body, hashlib.sha256).hexdigest()

    with patch("routers.webhook.process_inbound_message", new_callable=AsyncMock) as mock_process:
        request = MagicMock()
        request.body = AsyncMock(return_value=body)
        request.headers = {"X-Hub-Signature-256": sig}

        result = await receive_webhook(request)

    if hasattr(result, "status_code"):
        pytest.fail(f"Got HTTP {result.status_code} instead of JSON response")
    assert result["status"] == "pending_approval"
    mock_process.assert_not_called()


# ============================================================
# 22: REGRESSION TEST - ORIGINAL INCIDENT
# ============================================================


@pytest.mark.asyncio
async def test_regression_original_incident():
    """
    Replica el incidente real:
    - Cliente pide 3 Vienesa Gigante + 2 papas medianas
    - Bot responde correctamente con tags
    - Cliente pregunta "cuanto llevo?" → bot responde con items correctos
    - Cliente agrega una coca → total sube correctamente
    - Verifica: NUNCA se escaló incorrectamente
    - Verifica: orden final tiene exactamente los items correctos
    - Verifica: NO hay items alucinados (4 bebidas, "AS Gigante", etc.)
    """
    phone = "+56919999999"
    await _ensure_conversation(phone)

    # Turno 1: Cliente pide 3 vienesas gigantes italianas
    r1 = await turn(
        phone,
        "3 vienesas gigantes italianas",
        llm_response="3 Vienesa Gigante Italiana anotadas! [ORDER_ADD:completo_vienesa_gigante:3]",
    )
    assert r1.escalated is False
    assert len(r1.order["items"]) == 1
    assert r1.order["items"][0]["key"] == "completo_vienesa_gigante"
    assert r1.order["items"][0]["quantity"] == 3
    assert r1.order["items"][0]["price"] == 3400
    assert r1.order["total"] == 3400 * 3
    assert "[ORDER_ADD" not in r1.sent_text

    # Turno 2: Cliente pide 2 papas medianas
    r2 = await turn(
        phone,
        "y 2 papas fritas medianas",
        llm_response="2 Papas Fritas Mediana anotadas! [ORDER_ADD:papas_mediana:2]",
    )
    assert r2.escalated is False
    assert len(r2.order["items"]) == 2
    assert r2.order["total"] == 3400 * 3 + 3700 * 2

    # Turno 3: Cliente pregunta cuanto lleva - LLM tiene contexto de la orden
    # (en el incidente original, el bot alucinaba items por contexto viejo)
    r3 = await turn(
        phone,
        "cuanto llevo?",
        llm_response="Llevas 3x Vienesa Gigante Italiana ($3.400 c/u) y 2x Papas Fritas Mediana ($3.700 c/u). Total: $17.600",
    )
    assert r3.escalated is False
    # La orden no debio cambiar
    assert len(r3.order["items"]) == 2
    assert r3.order["total"] == 3400 * 3 + 3700 * 2

    # Turno 4: Cliente agrega una coca
    r4 = await turn(
        phone,
        "agrega una coca cola lata",
        llm_response="Coca Cola lata agregada! [ORDER_ADD:coca_lata:1]",
    )
    assert r4.escalated is False
    assert len(r4.order["items"]) == 3
    assert r4.order["total"] == 3400 * 3 + 3700 * 2 + 1500

    # Verificacion final: NO hay items alucinados
    all_keys = [i["key"] for i in r4.order["items"]]
    assert "completo_vienesa_gigante" in all_keys
    assert "papas_mediana" in all_keys
    assert "coca_lata" in all_keys
    # Items que el bot alucino en el incidente original NO deben estar
    assert "as_gigante" not in all_keys
    assert "fanta_lata" not in all_keys
    assert "sprite_lata" not in all_keys
    assert len(r4.order["items"]) == 3

    # Verificar que NUNCA se escalo en toda la conversacion
    conv = await db.get_conversation(phone)
    assert conv.state == "BOT_ACTIVE"

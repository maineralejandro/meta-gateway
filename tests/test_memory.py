import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from core.capabilities.cart import CartCapability as CartState
from core.container import container
from core.memory import WINDOW_SIZE, MemoryManager
from db.database import db
from db.models import Turn

cart_state = getattr(container, 'cart_capability', None) or CartState()


@pytest_asyncio.fixture(autouse=True)
async def setup_memory_test():
    from core.capabilities.base import registry
    from core.capabilities.cart import CartCapability
    registry.register(CartCapability)

    cart_state._carts.clear()
    cart_state._loaded_phones.clear()
    if not cart_state._catalog:
        cart_state._catalog = {
            "item_a": {"name": "Item A (standard)", "price": 3700},
            "item_b": {"name": "Item B (large)", "price": 4800},
            "item_c": {"name": "Item C Special", "price": 3400},
            "item_d": {"name": "Item D Combo", "price": 8900},
            "item_e": {"name": "Side E Medium", "price": 3700},
            "item_f": {"name": "Beverage F Can", "price": 1500},
        }
    yield

@pytest.mark.asyncio
async def test_build_context_no_memory():
    phone = "+56912345678"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    for i in range(5):
        await db.insert_turn(Turn(
            phone=phone,
            user_text=f"User msg {i}",
            assistant_text=f"Bot reply {i}",
        ))
    await db.commit()

    context = await manager.build_context(phone, agent_id=1)
    user_msgs = [c for c in context if c["role"] == "user"]
    asst_msgs = [c for c in context if c["role"] == "assistant"]
    assert len(user_msgs) == 5
    assert len(asst_msgs) == 5
    assert user_msgs[0]["content"] == "User msg 0"
    assert asst_msgs[-1]["content"] == "Bot reply 4"

@pytest.mark.asyncio
async def test_build_context_returns_recent_turns():
    phone = "+56919999999"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    for i in range(20):
        await db.insert_turn(Turn(
            phone=phone,
            user_text=f"User msg {i}",
            assistant_text=f"Bot reply {i}",
        ))

    context = await manager.build_context(phone, agent_id=1)
    user_msgs = [c for c in context if c["role"] == "user"]
    assert len(user_msgs) == WINDOW_SIZE
    assert user_msgs[0]["content"] == "User msg 4"
    assert user_msgs[-1]["content"] == "User msg 19"

@pytest.mark.asyncio
async def test_build_context_pending_message_not_in_turns():
    phone = "+56918888888"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    await db.insert_turn(Turn(
        phone=phone,
        user_text="Hola",
        assistant_text="Bienvenido",
    ))
    await db.execute(
        "INSERT INTO messages (phone, direction, source, text) VALUES ($1, 'inbound', 'customer', 'Quiero item')",
        phone,
    )
    await db.commit()

    context = await manager.build_context(phone, current_message="Quiero item", agent_id=1)
    texts = [c["content"] for c in context]
    assert "Quiero item" not in texts
    assert "Hola" in texts
    assert "Bienvenido" in texts

@pytest.mark.asyncio
async def test_build_context_with_memory():
    phone = "+56987654321"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    await db.upsert_memory(phone, "Resumen previo", json.dumps(["Dato 1"]), 10)
    await db.insert_turn(Turn(
        phone=phone,
        user_text="Hola",
        assistant_text="Bienvenido",
    ))
    await db.commit()

    context = await manager.build_context(phone, agent_id=1)
    system_msgs = [c for c in context if c["role"] == "system"]
    assert len(system_msgs) >= 1
    assert "Resumen previo" in system_msgs[0]["content"]

@pytest.mark.asyncio
async def test_build_context_filters_media():
    phone = "+56900000000"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    await db.insert_turn(Turn(
        phone=phone,
        user_text="[image]",
        assistant_text="Recibi tu imagen",
    ))
    await db.insert_turn(Turn(
        phone=phone,
        user_text="Duda",
        assistant_text="Respuesta",
    ))
    await db.insert_turn(Turn(
        phone=phone,
        user_text="[location] Calle 123",
        assistant_text="Ubicacion recibida",
    ))
    await db.commit()

    context = await manager.build_context(phone, agent_id=1)
    user_msgs = [c for c in context if c["role"] == "user"]
    asst_msgs = [c for c in context if c["role"] == "assistant"]
    assert len(user_msgs) == 3
    assert len(asst_msgs) == 3
    assert user_msgs[0]["content"] == "[mensaje multimedia]"
    assert user_msgs[1]["content"] == "Duda"
    assert user_msgs[2]["content"] == "[location] Calle 123"
    assert asst_msgs[0]["content"] == "Recibi tu imagen"


@pytest.mark.asyncio
async def test_build_context_burst_format_not_filtered():
    phone = "+56900001111"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    await db.insert_turn(Turn(
        phone=phone,
        user_text="[1] Hola\n\n[2] Quiero un item",
        assistant_text="Anotado!",
    ))
    await db.insert_turn(Turn(
        phone=phone,
        user_text="[1] Item D",
        assistant_text="Agregado!",
    ))
    await db.commit()

    context = await manager.build_context(phone, agent_id=1)
    user_msgs = [c for c in context if c["role"] == "user"]
    assert len(user_msgs) == 2
    assert "[1] Hola" in user_msgs[0]["content"]
    assert "[2] Quiero un item" in user_msgs[0]["content"]
    assert "[1] Item D" in user_msgs[1]["content"]


@pytest.mark.asyncio
async def test_build_context_mixed_media_and_burst():
    phone = "+56900002222"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    await db.insert_turn(Turn(
        phone=phone,
        user_text="[1] [audio]\n\n[2] Quiero un item",
        assistant_text="Anotado!",
    ))
    await db.insert_turn(Turn(
        phone=phone,
        user_text="[audio]",
        assistant_text="No puedo escuchar audios.",
    ))
    await db.commit()

    context = await manager.build_context(phone, agent_id=1)
    user_msgs = [c for c in context if c["role"] == "user"]
    assert len(user_msgs) == 2
    assert "[1] [audio]" in user_msgs[0]["content"]
    assert "[2] Quiero un item" in user_msgs[0]["content"]
    assert user_msgs[1]["content"] == "[mensaje multimedia]"

@pytest.mark.asyncio
async def test_build_context_guarantees_alternation():
    phone = "+56955555555"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    for i in range(10):
        await db.insert_turn(Turn(
            phone=phone,
            user_text=f"User {i}",
            assistant_text=f"Bot {i}",
        ))

    context = await manager.build_context(phone, agent_id=1)
    non_system = [c for c in context if c["role"] != "system"]
    for i in range(0, len(non_system) - 1, 2):
        assert non_system[i]["role"] == "user", f"Expected user at index {i}, got {non_system[i]['role']}"
        assert non_system[i + 1]["role"] == "assistant", f"Expected assistant at index {i+1}, got {non_system[i+1]['role']}"


@pytest.mark.asyncio
async def test_build_context_media_only_turn_gets_placeholder():
    phone = "+56955556666"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    await db.insert_turn(Turn(
        phone=phone,
        user_text="[audio]",
        assistant_text="No puedo escuchar audios, escribe tu mensaje.",
    ))
    await db.insert_turn(Turn(
        phone=phone,
        user_text="Quiero un item",
        assistant_text="Anotado!",
    ))
    await db.commit()

    context = await manager.build_context(phone, agent_id=1)
    user_msgs = [c for c in context if c["role"] == "user"]
    asst_msgs = [c for c in context if c["role"] == "assistant"]
    assert len(user_msgs) == 2
    assert len(asst_msgs) == 2
    assert user_msgs[0]["content"] == "[mensaje multimedia]"
    assert user_msgs[1]["content"] == "Quiero un item"

    non_system = [c for c in context if c["role"] != "system"]
    for i in range(0, len(non_system) - 1, 2):
        assert non_system[i]["role"] == "user", f"Media-only turn broke alternation at index {i}"


@pytest.mark.asyncio
async def test_build_context_empty_user_empty_assistant_skips_turn():
    phone = "+56955557777"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    await db.insert_turn(Turn(
        phone=phone,
        user_text="",
        assistant_text="",
    ))
    await db.insert_turn(Turn(
        phone=phone,
        user_text="Hola",
        assistant_text="Bienvenido",
    ))
    await db.commit()

    context = await manager.build_context(phone, agent_id=1)
    user_msgs = [c for c in context if c["role"] == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["content"] == "Hola"

@pytest.mark.asyncio
async def test_maybe_summarize_threshold():
    phone = "+56911112222"
    manager = MemoryManager()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({
        "summary": "Nuevo resumen",
        "key_facts": ["Fact A"]
    })

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    old_session_id = "old-session-1"
    await db.execute("INSERT INTO sessions (id, phone, ended_at) VALUES ($1, $2, '2025-01-01 00:00:00')", old_session_id, phone)
    for _ in range(15):
        await db.insert_turn(Turn(
            phone=phone,
            user_text="msg",
            assistant_text="reply",
            session_id=old_session_id,
        ))
    await db.insert_turn(Turn(phone=phone, user_text="current", assistant_text="reply"))

    with patch.object(manager._llm, "get_client", return_value=MagicMock()), \
         patch.object(manager._llm, "chat_completion", return_value=mock_response):
        await manager.maybe_summarize(phone)

    memory = await db.get_memory(phone)
    assert memory.summary == "Nuevo resumen"


@pytest.mark.asyncio
async def test_cart_state_add_item():
    state = CartState()
    state._catalog = {
        "item_c": {"name": "Item C Special", "price": 3400},
        "item_e": {"name": "Side E Medium", "price": 3700},
    }
    state._persist_or_revert = AsyncMock()
    state._ensure_loaded = AsyncMock()
    await state.add_item("+569", "item_c", 3)
    await state.add_item("+569", "item_e", 2)
    cart = await state.get_cart("+569")
    assert len(cart["items"]) == 2
    assert cart["total"] == 3400 * 3 + 3700 * 2
    assert cart["items"][0]["quantity"] == 3

    await state.add_item("+569", "item_c", 1)
    assert (await state.get_cart("+569"))["items"][0]["quantity"] == 4
    assert (await state.get_cart("+569"))["total"] == 3400 * 4 + 3700 * 2


@pytest.mark.asyncio
async def test_cart_state_format_for_context():
    state = CartState()
    state._catalog = {
        "item_c": {"name": "Item C Special", "price": 3400},
        "item_e": {"name": "Side E Medium", "price": 3700},
    }
    state._persist_or_revert = AsyncMock()
    state._ensure_loaded = AsyncMock()
    result = await state.format_for_context("+569")
    assert result is not None
    assert "Catalogo disponible" in result

    await state.add_item("+569", "item_c", 3)
    await state.add_item("+569", "item_e", 2)
    result = await state.format_for_context("+569")
    assert "Item C Special" in result
    assert "Side E Medium" in result
    assert "Total:" in result


@pytest.mark.asyncio
async def test_cart_state_unknown_item():
    state = CartState()
    state._persist = AsyncMock()
    state._ensure_loaded = AsyncMock()
    await state.add_item("+569", "item_inexistente", 1)
    assert (await state.get_cart("+569"))["items"] == []


@pytest.mark.asyncio
async def test_cart_state_format_for_context_injects_cart():
    phone = "+56917777777"
    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    await db.commit()

    ctx = await cart_state.format_for_context(phone, {})
    assert ctx is not None
    assert "vacio" in ctx

    await cart_state.add_item(phone, "item_c", 3)
    await cart_state.add_item(phone, "item_e", 2)

    ctx = await cart_state.format_for_context(phone, {})
    assert ctx is not None
    assert "Item C Special" in ctx
    assert "Total:" in ctx


@pytest.mark.asyncio
async def test_build_context_includes_episodic_memory():
    phone = "+56922223333"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    old_session_id = "episodic-old-1"
    new_session_id = "episodic-new-1"
    await db.execute("INSERT INTO sessions (id, phone, started_at, summary) VALUES ($1, $2, '2025-05-05 10:00', 'Sesión del 2025-05-05 10:00 — El cliente pidió un item.')", old_session_id, phone)
    await db.execute("INSERT INTO sessions (id, phone, started_at) VALUES ($1, $2, '2025-05-05 15:00')", new_session_id, phone)
    await db.insert_turn(Turn(phone=phone, user_text="Hola", assistant_text="Hola!", session_id=new_session_id))
    await db.commit()

    context = await manager.build_context(phone, agent_id=1)
    system_msgs = [c for c in context if c["role"] == "system"]
    episodic_msgs = [c for c in system_msgs if "sesiones anteriores" in c["content"].lower()]
    assert len(episodic_msgs) == 1
    assert "item" in episodic_msgs[0]["content"]


@pytest.mark.asyncio
async def test_build_context_session_boundary_marker():
    phone = "+56944445555"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    session_a = "sess-boundary-a"
    session_b = "sess-boundary-b"
    await db.execute("INSERT INTO sessions (id, phone) VALUES ($1, $2)", session_a, phone)
    await db.execute("INSERT INTO sessions (id, phone) VALUES ($1, $2)", session_b, phone)
    await db.insert_turn(Turn(phone=phone, user_text="Msg A1", assistant_text="Reply A1", session_id=session_a))
    await db.insert_turn(Turn(phone=phone, user_text="Msg B1", assistant_text="Reply B1", session_id=session_b))
    await db.commit()

    context = await manager.build_context(phone, agent_id=1)
    user_msgs = [c for c in context if c["role"] == "user"]
    system_boundary = [c for c in context if c["role"] == "system" and "Sesión anterior" in c["content"]]
    assert len(system_boundary) == 0
    boundary_user = [m for m in user_msgs if m["content"].startswith("--- Sesión anterior ---")]
    assert len(boundary_user) == 1
    assert "Msg B1" in boundary_user[0]["content"]


@pytest.mark.asyncio
async def test_build_context_no_system_messages_between_turns():
    phone = "+56944445556"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    session_a = "sess-nosys-a"
    session_b = "sess-nosys-b"
    await db.execute("INSERT INTO sessions (id, phone) VALUES ($1, $2)", session_a, phone)
    await db.execute("INSERT INTO sessions (id, phone) VALUES ($1, $2)", session_b, phone)
    await db.insert_turn(Turn(phone=phone, user_text="Msg A1", assistant_text="Reply A1", session_id=session_a))
    await db.insert_turn(Turn(phone=phone, user_text="Msg B1", assistant_text="Reply B1", session_id=session_b))
    await db.commit()

    context = await manager.build_context(phone, agent_id=1)
    first_non_system = next(i for i, m in enumerate(context) if m["role"] != "system")
    trailing_system = [m for m in context[first_non_system:] if m["role"] == "system"]
    assert len(trailing_system) == 0
    phone = "+56966667777"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    current_sid = "sess-current-only"
    await db.execute("INSERT INTO sessions (id, phone, started_at, summary) VALUES ($1, $2, '2025-05-05 10:00', 'Resumen de la sesión actual')", current_sid, phone)
    await db.insert_turn(Turn(phone=phone, user_text="Hola", assistant_text="Hola!", session_id=current_sid))
    await db.commit()

    context = await manager.build_context(phone, agent_id=1)
    system_msgs = [c for c in context if c["role"] == "system"]
    episodic_msgs = [c for c in system_msgs if "sesiones anteriores" in c["content"].lower()]
    assert len(episodic_msgs) == 0


@pytest.mark.asyncio
async def test_summarize_session():
    phone = "+56988889999"
    manager = MemoryManager()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Sesión del 2025-05-05 — El cliente pidió un item con todo y una bebida."

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    session_id = "summarize-sess-1"
    await db.execute("INSERT INTO sessions (id, phone, started_at) VALUES ($1, $2, '2025-05-05 14:23')", session_id, phone)
    await db.insert_turn(Turn(phone=phone, user_text="Hola, quiero un item", assistant_text="Con todo?", session_id=session_id))
    await db.insert_turn(Turn(phone=phone, user_text="Sí, con todo y una bebida", assistant_text="Perfecto!", session_id=session_id))
    await db.commit()

    with patch.object(manager._llm, "get_client", return_value=MagicMock()), \
         patch.object(manager._llm, "chat_completion", return_value=mock_response):
        await manager.summarize_session(phone, session_id)

    row = await db.fetchone("SELECT summary FROM sessions WHERE id=$1", session_id)
    assert row["summary"] is not None
    assert "item" in row["summary"]


@pytest.mark.asyncio
async def test_summarize_session_no_turns():
    phone = "+56999990001"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    session_id = "empty-sess-1"
    await db.execute("INSERT INTO sessions (id, phone) VALUES ($1, $2)", session_id, phone)
    await db.commit()

    with patch.object(manager._llm, "get_client", return_value=MagicMock()):
        await manager.summarize_session(phone, session_id)

    row = await db.fetchone("SELECT summary FROM sessions WHERE id=$1", session_id)
    assert row["summary"] is None


@pytest.mark.asyncio
async def test_maybe_summarize_skips_current_session():
    phone = "+56911113333"
    manager = MemoryManager()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({
        "summary": "Resumen de sesión antigua",
        "key_facts": ["Hecho viejo"]
    })

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)
    old_session = "old-sess-for-summarize"
    new_session = "new-sess-for-summarize"
    await db.execute("INSERT INTO sessions (id, phone, ended_at) VALUES ($1, $2, '2025-01-01')", old_session, phone)
    await db.execute("INSERT INTO sessions (id, phone) VALUES ($1, $2)", new_session, phone)

    for _ in range(15):
        await db.insert_turn(Turn(phone=phone, user_text="old msg", assistant_text="old reply", session_id=old_session))
    for _ in range(3):
        await db.insert_turn(Turn(phone=phone, user_text="new msg", assistant_text="new reply", session_id=new_session))

    with patch.object(manager._llm, "get_client", return_value=MagicMock()), \
         patch.object(manager._llm, "chat_completion", return_value=mock_response):
        await manager.maybe_summarize(phone)

    memory = await db.get_memory(phone)
    assert memory.summary == "Resumen de sesión antigua"

    all_turns = await db.get_turns(phone, limit=100)
    current_session_turns = [t for t in all_turns if t.session_id == new_session]
    assert len(current_session_turns) == 3


def test_format_turn_user_text_burst_not_filtered():
    result = MemoryManager._format_turn_user_text("[1] Hola\n\n[2] Quiero un item")
    assert result is not None
    assert "[1] Hola" in result
    assert "[2] Quiero un item" in result


def test_format_turn_user_text_media_filtered():
    assert MemoryManager._format_turn_user_text("[image]") is None
    assert MemoryManager._format_turn_user_text("[audio]") is None
    assert MemoryManager._format_turn_user_text("[video]") is None
    assert MemoryManager._format_turn_user_text("[document]") is None


def test_format_turn_user_text_location_kept():
    result = MemoryManager._format_turn_user_text("[location] Calle 123")
    assert result is not None
    assert "[location] Calle 123" in result


def test_format_turn_user_text_mixed_media_and_text():
    result = MemoryManager._format_turn_user_text("[1] [audio]\n\n[2] Quiero un item")
    assert result is not None
    assert "[1] [audio]" in result
    assert "[2] Quiero un item" in result


def test_format_turn_user_text_empty():
    assert MemoryManager._format_turn_user_text("") is None
    assert MemoryManager._format_turn_user_text("[image]\n\n[audio]") is None

import json
import os
from contextlib import suppress
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from core.memory import WINDOW_SIZE, MemoryManager
from core.order_state import OrderState, order_state
from db.database import close_db, db, init_db


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_session_db():
    os.environ["DB_DIR"] = "./tests/data"
    os.environ["DB_NAME"] = "test_memory.db"
    os.environ["DB_PATH"] = "./tests/data/test_memory.db"

    os.makedirs("./tests/data", exist_ok=True)
    if os.path.exists("./tests/data/test_memory.db"):
        with suppress(PermissionError):
            os.remove("./tests/data/test_memory.db")

    await init_db()
    with open("db/schema.sql") as f:
        schema = f.read()
    await db._conn.executescript(schema)
    await db.commit()

    yield
    await close_db()


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    await db.execute("DELETE FROM messages")
    await db.execute("DELETE FROM conversation_memory")
    await db.execute("DELETE FROM escalation_events")
    await db.execute("DELETE FROM agent_decisions")
    await db.execute("DELETE FROM orders")
    await db.execute("UPDATE conversations SET current_session_id = NULL")
    await db.execute("DELETE FROM sessions")
    await db.execute("DELETE FROM conversations")
    await db.execute("DELETE FROM agents")
    await db.execute("INSERT INTO agents (id, name, system_prompt) VALUES (1, 'Default Agent', 'Prompt')")
    await db.commit()
    order_state._orders.clear()
    order_state._loaded_phones.clear()

    @pytest.mark.asyncio
    async def test_build_context_no_memory():
        phone = "+56912345678"
        manager = MemoryManager()

        await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", (phone,))
        for i in range(5):
            await db.execute(
                "INSERT INTO messages (phone, direction, source, text) VALUES (?, ?, ?, ?)",
                (phone, "inbound" if i % 2 == 0 else "outbound", "customer" if i % 2 == 0 else "bot", f"Mensaje {i}")
            )
        await db.commit()

        context = await manager.build_context(phone)
        assert len(context) == 5
        assert context[0]["role"] == "user"
        assert context[0]["content"] == "Mensaje 0"
        assert context[-1]["content"] == "Mensaje 4"

    @pytest.mark.asyncio
    async def test_build_context_returns_recent_messages():
        phone = "+56919999999"
        manager = MemoryManager()

        await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", (phone,))
        for i in range(20):
            await db.execute(
                "INSERT INTO messages (phone, direction, source, text) VALUES (?, ?, ?, ?)",
                (phone, "inbound" if i % 2 == 0 else "outbound", "customer" if i % 2 == 0 else "bot", f"Mensaje {i}")
            )
        await db.commit()

        context = await manager.build_context(phone)
        assert len(context) == WINDOW_SIZE
        assert context[0]["content"] == "Mensaje 4"
        assert context[-1]["content"] == "Mensaje 19"

    @pytest.mark.asyncio
    async def test_build_context_excludes_current_message():
        phone = "+56918888888"
        manager = MemoryManager()

        await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", (phone,))
        await db.execute(
            "INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', 'Hola')",
            (phone,)
        )
        await db.execute(
            "INSERT INTO messages (phone, direction, source, text) VALUES (?, 'outbound', 'bot', 'Bienvenido')",
            (phone,)
        )
        await db.execute(
            "INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', 'Quiero completo')",
            (phone,)
        )
        await db.commit()

        context = await manager.build_context(phone, current_message="Quiero completo")
        texts = [c["content"] for c in context]
        assert "Quiero completo" not in texts
        assert "Hola" in texts
        assert "Bienvenido" in texts

@pytest.mark.asyncio
async def test_build_context_with_memory():
    phone = "+56987654321"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", (phone,))
    await db.upsert_memory(phone, "Resumen previo", json.dumps(["Dato 1"]), 10)
    await db.execute(
        "INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', 'Hola')",
        (phone,)
    )
    await db.commit()

    context = await manager.build_context(phone)
    assert len(context) == 2
    assert context[0]["role"] == "system"
    assert "Resumen previo" in context[0]["content"]

@pytest.mark.asyncio
async def test_build_context_filters_media():
    phone = "+56900000000"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", (phone,))
    await db.execute("INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', '[image]')", (phone,))
    await db.execute("INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', 'Duda')", (phone,))
    await db.execute("INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', '[location] Calle 123')", (phone,))
    await db.commit()

    context = await manager.build_context(phone)
    assert len(context) == 2
    assert context[0]["content"] == "Duda"
    assert context[1]["content"] == "[location] Calle 123"

@pytest.mark.asyncio
@patch("core.memory.AsyncOpenAI")
async def test_maybe_summarize_threshold(mock_openai_class):
    phone = "+56911112222"
    manager = MemoryManager()

    mock_client = AsyncMock()
    mock_openai_class.return_value = mock_client

    with patch("core.memory.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "sk-test"
        mock_settings.LLM_BASE_URL = "https://api.openai.com/v1"
        mock_settings.LLM_MODEL = "gpt-3.5-turbo"

        await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", (phone,))
        for _ in range(15):
            await db.execute("INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', 'msg')", (phone,))
        await db.commit()

        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = json.dumps({
            "summary": "Nuevo resumen",
            "key_facts": ["Fact A"]
        })
        mock_client.chat.completions.create.return_value = mock_response

        await manager.maybe_summarize(phone)

        memory = await db.get_memory(phone)
        assert memory.summary == "Nuevo resumen"
        assert memory.total_messages_summarized == 15


@pytest.mark.asyncio
async def test_order_state_add_item():
    state = OrderState()
    await state.add_item("+569", "completo_vienesa_gigante", 3)
    await state.add_item("+569", "papas_mediana", 2)
    order = await state.get_order("+569")
    assert len(order["items"]) == 2
    assert order["total"] == 3400 * 3 + 3700 * 2
    assert order["items"][0]["quantity"] == 3

    await state.add_item("+569", "completo_vienesa_gigante", 1)
    assert (await state.get_order("+569"))["items"][0]["quantity"] == 4
    assert (await state.get_order("+569"))["total"] == 3400 * 4 + 3700 * 2


@pytest.mark.asyncio
async def test_order_state_parse_tags():
    state = OrderState()
    cleaned = await state.parse_tags("+569", "Anotado! [ORDER_ADD:completo_vienesa_gigante:3][ORDER_ADD:papas_mediana:2]")
    assert cleaned == "Anotado!"
    order = await state.get_order("+569")
    assert len(order["items"]) == 2
    assert order["total"] == 3400 * 3 + 3700 * 2


@pytest.mark.asyncio
async def test_order_state_parse_remove_tag():
    state = OrderState()
    await state.add_item("+569", "completo_vienesa_gigante", 3)
    await state.parse_tags("+569", "Quitado [ORDER_REMOVE:completo_vienesa_gigante:1]")
    assert (await state.get_order("+569"))["items"][0]["quantity"] == 2


@pytest.mark.asyncio
async def test_order_state_parse_clear_tag():
    state = OrderState()
    await state.add_item("+569", "completo_vienesa_gigante", 3)
    await state.parse_tags("+569", "Empezamos de cero [ORDER_CLEAR]")
    assert (await state.get_order("+569"))["items"] == []


@pytest.mark.asyncio
async def test_order_state_format_for_context():
    state = OrderState()
    result = await state.format_for_context("+569")
    assert result is None

    await state.add_item("+569", "completo_vienesa_gigante", 3)
    await state.add_item("+569", "papas_mediana", 2)
    result = await state.format_for_context("+569")
    assert "Vienesa Gigante Italiana" in result
    assert "Papas Fritas Mediana" in result
    assert "Total:" in result


@pytest.mark.asyncio
async def test_order_state_unknown_item():
    state = OrderState()
    await state.add_item("+569", "item_inexistente", 1)
    assert (await state.get_order("+569"))["items"] == []


@pytest.mark.asyncio
async def test_build_context_includes_order_state():
    phone = "+56917777777"
    manager = MemoryManager()

    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", (phone,))
    await db.execute(
        "INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', 'Hola')",
        (phone,)
    )
    await db.commit()

    await order_state.add_item(phone, "completo_vienesa_gigante", 3)
    await order_state.add_item(phone, "papas_mediana", 2)

    context = await manager.build_context(phone)
    system_msgs = [c for c in context if c["role"] == "system"]
    order_msgs = [c for c in system_msgs if "Pedido actual" in c["content"]]
    assert len(order_msgs) == 1
    assert "Vienesa Gigante Italiana" in order_msgs[0]["content"]
    assert "Total:" in order_msgs[0]["content"]

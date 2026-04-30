import pytest
import pytest_asyncio
import os
import json
import asyncio
from unittest.mock import AsyncMock, patch
from core.memory import MemoryManager, WINDOW_SIZE, SUMMARIZE_THRESHOLD
from db.database import db, init_db, close_db
from db.models import Message, ConversationMemory

# Fixture de sesión para inicializar la base de datos una sola vez
@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_session_db():
    os.environ["DB_DIR"] = "./tests/data"
    os.environ["DB_NAME"] = "test_memory.db"
    os.environ["DB_PATH"] = "./tests/data/test_memory.db"
    
    os.makedirs("./tests/data", exist_ok=True)
    if os.path.exists("./tests/data/test_memory.db"):
        try:
            os.remove("./tests/data/test_memory.db")
        except PermissionError:
            pass # A veces el archivo queda bloqueado momentáneamente
    
    await init_db()
    # Asegurar que el esquema sea el último (incluyendo conversation_memory)
    with open("db/schema.sql", "r") as f:
        schema = f.read()
        await db._conn.executescript(schema)
        await db.commit()
    
    yield
    await close_db()

# Fixture de función para limpiar tablas antes de cada test
@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    await db.execute("DELETE FROM messages")
    await db.execute("DELETE FROM conversation_memory")
    await db.execute("DELETE FROM escalation_events")
    await db.execute("DELETE FROM agent_decisions")
    await db.execute("DELETE FROM agents")
    await db.execute("DELETE FROM conversations")
    # Agente por defecto
    await db.execute("INSERT INTO agents (id, name, system_prompt) VALUES (1, 'Default Agent', 'Prompt')")
    await db.commit()

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
        for i in range(15):
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

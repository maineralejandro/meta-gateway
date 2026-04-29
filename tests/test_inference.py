import pytest
import os
import sys
import sqlite3
import aiosqlite
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.inference import InferenceEngine
from db.database import db as global_db
from db.models import Agent

TEST_DB_PATH = "/tmp/hermes_test/test_inference.db"

@pytest.fixture(autouse=True)
async def setup_test_db():
    os.makedirs("/tmp/hermes_test", exist_ok=True)
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    from core.config import settings
    settings.DB_PATH = TEST_DB_PATH

    schema_path = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
    with open(schema_path) as f:
        schema = f.read()

    sync_conn = sqlite3.connect(TEST_DB_PATH)
    sync_conn.executescript(schema)
    sync_conn.close()

    if global_db._conn:
        await global_db._conn.close()
    global_db._conn = None
    global_db._conn = await aiosqlite.connect(TEST_DB_PATH)
    global_db._conn.row_factory = aiosqlite.Row

    yield

    if global_db._conn:
        await global_db._conn.close()
        global_db._conn = None
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

@pytest.mark.asyncio
async def test_inference_loads_from_db():
    # Insert a test agent
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("Test Bot", "You are a test prompt.", 1)
    )
    await global_db.commit()

    engine = InferenceEngine()
    
    # Mock OpenAI client
    mock_client = AsyncMock()
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(content="Hello!"))]
    mock_client.chat.completions.create.return_value = mock_response

    with patch.object(engine, '_get_client', return_value=mock_client):
        # Set available to True for test
        engine._available = True
        
        response, escalate = await engine.generate("Hi")
        
        # Verify it used the prompt from DB
        args, kwargs = mock_client.chat.completions.create.call_args
        messages = kwargs['messages']
        assert messages[0]['content'] == "You are a test prompt."
        assert response == "Hello!"
        assert escalate is False

@pytest.mark.asyncio
async def test_inference_fallback_from_db():
    # Insert agent with custom fallbacks
    fallbacks = '{"greeting": "Custom hello", "default": "Custom what?"}'
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, fallback_responses, is_active) VALUES (?, ?, ?, ?)",
        ("Fallback Bot", "...", fallbacks, 1)
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._available = False # Force fallback
    
    response, escalate = await engine.generate("hola")
    assert response == "Custom hello"
    
    response, escalate = await engine.generate("unknown")
    assert response == "Custom what?"

import os
import sqlite3
import sys
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.inference import InferenceEngine, _normalize_roles
from db.database import db as global_db

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
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("Test Bot", "You are a test prompt.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Hello!"))]
    mock_response.usage = None

    with patch.object(engine._llm, "chat_completion", return_value=mock_response), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        engine._llm._available = True
        response, escalate, _trace = await engine.generate("Hi")

    assert response == "Hello!"
    assert escalate is False


@pytest.mark.asyncio
async def test_inference_fallback_from_db():
    fallbacks = '{"greeting": "Custom hello", "default": "Custom what?"}'
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, fallback_responses, is_active) VALUES (?, ?, ?, ?)",
        ("Fallback Bot", "...", fallbacks, 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = False

    response, _escalate, _trace = await engine.generate("hola")
    assert response == "Custom hello"

    response, _escalate, _trace = await engine.generate("unknown")
    assert response == "Custom what?"


@pytest.mark.asyncio
async def test_escalation_marker_detected():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, escalation_marker, is_active) VALUES (?, ?, ?, ?)",
        ("Esc Bot", "Be helpful.", "ESCALATE_TO_HUMAN", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ESCALATE_TO_HUMAN I need help"))]
    mock_response.usage = None

    with patch.object(engine._llm, "chat_completion", return_value=mock_response), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        engine._llm._available = True
        response, escalated, _trace = await engine.generate("I'm upset")

    assert escalated is True
    assert "ESCALATE_TO_HUMAN" not in response
    assert "I need help" in response


@pytest.mark.asyncio
async def test_escalation_marker_empty_clean():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, escalation_marker, is_active) VALUES (?, ?, ?, ?)",
        ("Esc Bot2", "Be helpful.", "ESCALATE_TO_HUMAN", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=" ESCALATE_TO_HUMAN "))]
    mock_response.usage = None

    with patch.object(engine._llm, "chat_completion", return_value=mock_response), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        engine._llm._available = True
        response, escalated, _trace = await engine.generate("help")

    assert escalated is True
    assert "atendedor" in response


@pytest.mark.asyncio
async def test_retry_on_rate_limit():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("Retry Bot", "Be helpful.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    good_response = MagicMock()
    good_response.choices = [MagicMock(message=MagicMock(content="Hello!"))]
    good_response.usage = None

    with patch.object(engine._llm, "chat_completion", return_value=good_response), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        engine._llm._available = True
        response, _escalated, _trace = await engine.generate("Hi")

    assert response == "Hello!"


@pytest.mark.asyncio
async def test_all_retries_fail_falls_back():
    from openai import RateLimitError

    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, fallback_responses, is_active) VALUES (?, ?, ?, ?)",
        ("Fail Bot", "Be helpful.", '{"greeting": "Fallback!", "default": "Default!"}', 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    with patch.object(engine._llm, "chat_completion", side_effect=RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body=None,
    )), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        engine._llm._available = True
        response, escalated, _trace = await engine.generate("hola")

    assert response == "Fallback!"
    assert escalated is False


@pytest.mark.asyncio
async def test_generic_exception_falls_back():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, fallback_responses, is_active) VALUES (?, ?, ?, ?)",
        ("Exc Bot", "Be helpful.", '{"default": "Error fallback"}', 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    with patch.object(engine._llm, "chat_completion", side_effect=RuntimeError("unexpected")), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        engine._llm._available = True
        response, _escalated, _trace = await engine.generate("test")

    assert "Error fallback" in response


@pytest.mark.asyncio
async def test_client_none_returns_fallback():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, fallback_responses, is_active) VALUES (?, ?, ?, ?)",
        ("NoClient Bot", "Be helpful.", '{"default": "no client"}', 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = True

    with patch.object(engine._llm, "get_client", return_value=None):
        response, _escalated, _trace = await engine.generate("test")

    assert "no client" in response


@pytest.mark.asyncio
async def test_response_with_usage():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("Usage Bot", "Be helpful.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Hello!"))]
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 50
    mock_response.usage.completion_tokens = 20

    with patch.object(engine._llm, "chat_completion", return_value=mock_response), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()), \
         patch("core.inference.LLM_TOKENS_PROMPT") as mock_prompt, \
         patch("core.inference.LLM_TOKENS_COMPLETION") as mock_comp:
        engine._llm._available = True
        response, _escalated, _trace = await engine.generate("Hi")

    assert response == "Hello!"
    mock_prompt.inc.assert_called_once_with(50)
    mock_comp.inc.assert_called_once_with(20)


@pytest.mark.asyncio
async def test_response_none_content():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("NoneContent Bot", "Be helpful.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=None))]
    mock_response.usage = None

    with patch.object(engine._llm, "chat_completion", return_value=mock_response), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        engine._llm._available = True
        response, escalated, _trace = await engine.generate("Hi")

    assert response == ""
    assert escalated is False


@pytest.mark.asyncio
async def test_get_client_lazy_init():
    engine = InferenceEngine()
    engine._llm._available = True
    engine._llm._client = None

    with patch("core.llm_client.AsyncOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        client = engine._llm.get_client()

    assert client is not None
    mock_openai.assert_called_once()


@pytest.mark.asyncio
async def test_get_client_not_available():
    engine = InferenceEngine()
    engine._llm._available = False
    engine._llm._client = None

    client = engine._llm.get_client()
    assert client is None


@pytest.mark.asyncio
async def test_fallback_price_query():
    fallbacks = '{"price": "Precios: completo $3000"}'
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, fallback_responses, is_active) VALUES (?, ?, ?, ?)",
        ("Price Bot", "...", fallbacks, 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = False

    response, _, _trace = await engine.generate("cuanto cuesta el completo")
    assert "3000" in response


@pytest.mark.asyncio
async def test_fallback_promo_query():
    fallbacks = '{"promo": "2x1 en completos hoy"}'
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, fallback_responses, is_active) VALUES (?, ?, ?, ?)",
        ("Promo Bot", "...", fallbacks, 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = False

    response, _, _trace = await engine.generate("hay alguna oferta?")
    assert "2x1" in response


@pytest.mark.asyncio
async def test_fallback_delivery_query():
    fallbacks = '{"delivery": "Delivery en 30 min"}'
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, fallback_responses, is_active) VALUES (?, ?, ?, ?)",
        ("Delivery Bot", "...", fallbacks, 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = False

    response, _, _trace = await engine.generate("hacen delivery?")
    assert "30 min" in response


@pytest.mark.asyncio
async def test_reload():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("Reload Bot", "Original prompt.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    await engine.reload()


def test_normalize_roles_merges_consecutive_same():
    messages = [
        {"role": "system", "content": "A"},
        {"role": "system", "content": "B"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = _normalize_roles(messages)
    assert len(result) == 3
    assert result[0]["content"] == "A\n\nB"
    assert result[1]["role"] == "user"
    assert result[2]["role"] == "assistant"


def test_normalize_roles_fixes_assistant_first():
    messages = [
        {"role": "system", "content": "prompt"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "hi"},
    ]
    result = _normalize_roles(messages)
    non_system = [m for m in result if m["role"] != "system"]
    assert non_system[0]["role"] == "user"
    assert non_system[1]["role"] == "assistant"
    assert non_system[2]["role"] == "user"


def test_normalize_roles_no_fix_needed():
    messages = [
        {"role": "system", "content": "prompt"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = _normalize_roles(messages)
    assert len(result) == 3
    assert result[1]["role"] == "user"
    assert result[2]["role"] == "assistant"


def test_normalize_roles_assistant_only_after_system():
    messages = [
        {"role": "system", "content": "prompt"},
        {"role": "assistant", "content": "Welcome!"},
    ]
    result = _normalize_roles(messages)
    non_system = [m for m in result if m["role"] != "system"]
    assert len(non_system) == 2
    assert non_system[0]["role"] == "user"
    assert non_system[0]["content"] == "[mensaje anterior]"
    assert non_system[1]["role"] == "assistant"

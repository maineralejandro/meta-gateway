import json
import os
import sqlite3
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.inference import ESCALATE_TOOL_SCHEMA, GenerationResult, InferenceEngine, _build_tool_map
from core.order_state import OrderState
from db.database import db as global_db

TEST_DB_PATH = "/tmp/hermes_test/test_tool_loop.db"


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


def _make_tool_call(tc_id: str, name: str, args: dict) -> MagicMock:
    tc = MagicMock()
    tc.id = tc_id
    tc.type = "function"
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _make_text_response(text: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    resp.choices[0].message.tool_calls = None
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    return resp


def _make_tool_response(tool_calls: list[MagicMock], content: str | None = None, prompt_tokens: int = 10, completion_tokens: int = 5) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].message.tool_calls = tool_calls
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    return resp


@pytest.mark.asyncio
async def test_generate_with_tools_single_tool_call():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("Tool Bot", "Eres un asistente.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = True

    order_cap = OrderState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()

    tc = _make_tool_call("tc1", "order_add", {"item_key": "completo_normal", "qty": 2})
    tool_response = _make_tool_response([tc])
    text_response = _make_text_response("Tu pedido tiene 2 completos normales.")

    call_count = 0

    async def mock_chat_completion(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return tool_response
        return text_response

    with patch.object(engine._llm, "chat_completion", side_effect=mock_chat_completion), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        text, escalated, trace = await engine.generate(
            "Quiero 2 completos", capabilities=[order_cap], phone="+56910000001",
        )

    assert "completos" in text.lower() or "pedido" in text.lower()
    assert escalated is False
    assert trace.get("tools_executed") is not None
    assert trace.get("tool_loop_iterations") == 2


@pytest.mark.asyncio
async def test_generate_with_tools_escalate():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("Esc Bot", "Eres un asistente.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = True

    order_cap = OrderState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()

    tc = _make_tool_call("tc_esc", "escalate_to_human", {"reason": "client upset"})
    tool_response = _make_tool_response([tc])

    with patch.object(engine._llm, "chat_completion", return_value=tool_response), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        _text, escalated, trace = await engine.generate(
            "Estoy molesto", capabilities=[order_cap], phone="+56910000001",
        )

    assert escalated is True
    assert trace.get("escalation_reason") == "client upset"


@pytest.mark.asyncio
async def test_generate_with_tools_loop_detection():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("Loop Bot", "Eres un asistente.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = True

    order_cap = OrderState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()

    tc1 = _make_tool_call("tc1", "order_add", {"item_key": "invalid_key", "qty": 1})
    tc2 = _make_tool_call("tc2", "order_add", {"item_key": "invalid_key", "qty": 1})

    call_count = 0

    async def mock_chat_completion(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return _make_tool_response([tc1 if call_count == 1 else tc2])
        return _make_text_response("No pude agregar ese item.")

    with patch.object(engine._llm, "chat_completion", side_effect=mock_chat_completion), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        text, _escalated, _trace = await engine.generate(
            "Agrega algo invalido", capabilities=[order_cap], phone="+56910000001",
        )

    assert "invalid" in text.lower() or "item" in text.lower() or "no pude" in text.lower()
    assert call_count == 3


@pytest.mark.asyncio
async def test_generate_with_tools_max_iterations():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("MaxIter Bot", "Eres un asistente.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = True

    order_cap = OrderState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()

    tc = _make_tool_call("tc_loop", "order_add", {"item_key": "completo_normal", "qty": 1})

    async def mock_chat_completion(messages, **kwargs):
        return _make_tool_response([tc])

    with patch.object(engine._llm, "chat_completion", side_effect=mock_chat_completion), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        _text, escalated, trace = await engine.generate(
            "loop test", capabilities=[order_cap], phone="+56910000001",
        )

    assert escalated is True
    assert trace.get("escalation_reason") == "tool_loop_max_iterations"


@pytest.mark.asyncio
async def test_generate_with_tools_unknown_tool():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("Unknown Bot", "Eres un asistente.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = True

    order_cap = OrderState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()

    tc = _make_tool_call("tc_unk", "nonexistent_tool", {})
    tool_response = _make_tool_response([tc])
    text_response = _make_text_response("Esa herramienta no existe.")

    call_count = 0

    async def mock_chat_completion(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return tool_response
        return text_response

    with patch.object(engine._llm, "chat_completion", side_effect=mock_chat_completion), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        text, escalated, _trace = await engine.generate(
            "test unknown", capabilities=[order_cap], phone="+56910000001",
        )

    assert "herramienta" in text.lower() or "no existe" in text.lower()
    assert escalated is False


@pytest.mark.asyncio
async def test_generate_without_tools_uses_tag_flow():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("Tag Bot", "Eres un asistente.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = True

    no_tool_cap = MagicMock()
    no_tool_cap.get_tool_definitions = MagicMock(return_value=[])
    no_tool_cap.get_tool_names = MagicMock(return_value=set())
    no_tool_cap.get_prompt_instructions = MagicMock(return_value="")

    text_response = _make_text_response("Hola!")

    with patch.object(engine._llm, "chat_completion", return_value=text_response), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        text, escalated, trace = await engine.generate(
            "hola", capabilities=[no_tool_cap], phone="+56910000001",
        )

    assert text == "Hola!"
    assert escalated is False
    assert trace.get("tools_executed") is None


@pytest.mark.asyncio
async def test_generate_escalation_string_fallback_in_tool_mode():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, escalation_marker, is_active) VALUES (?, ?, ?, ?)",
        ("EscStr Bot", "Eres un asistente.", "ESCALATE_TO_HUMAN", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = True

    order_cap = OrderState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()

    text_response = _make_text_response("ESCALATE_TO_HUMAN I need help")

    with patch.object(engine._llm, "chat_completion", return_value=text_response), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        _text, escalated, _trace = await engine.generate(
            "help", capabilities=[order_cap], phone="+56910000001",
        )

        assert escalated is True
        assert "ESCALATE_TO_HUMAN" not in _text


def test_generation_result_to_tuple():
    result = GenerationResult(
        text="Test",
        should_escalate=True,
        escalation_reason="test_reason",
        tools_executed=[{"tool": "t1"}],
        iterations=3,
        prompt_tokens=100,
        completion_tokens=50,
    )
    text, escalated, trace = result.to_tuple()
    assert text == "Test"
    assert escalated is True
    assert trace["escalation_reason"] == "test_reason"
    assert trace["tool_loop_iterations"] == 3
    assert json.loads(trace["tools_executed"]) == [{"tool": "t1"}]


def test_generation_result_to_tuple_no_tools():
    result = GenerationResult(text="Hello")
    _text, _escalated, trace = result.to_tuple()
    assert trace["tools_executed"] is None
    assert trace["escalation_reason"] is None


def test_build_tool_map():
    order_cap = OrderState()
    lead_cap = MagicMock()
    lead_cap.get_tool_names = MagicMock(return_value={"lead_get", "lead_update_field"})

    tool_map = _build_tool_map([order_cap, lead_cap])
    assert "order_add" in tool_map
    assert "order_get_menu" in tool_map
    assert "lead_get" in tool_map
    assert "lead_update_field" in tool_map
    assert tool_map["order_add"] is order_cap
    assert tool_map["lead_get"] is lead_cap


def test_escalate_tool_schema_structure():
    assert ESCALATE_TOOL_SCHEMA["type"] == "function"
    func = ESCALATE_TOOL_SCHEMA["function"]
    assert func["name"] == "escalate_to_human"
    assert "reason" in func["parameters"]["properties"]
    assert "reason" in func["parameters"]["required"]
    assert "no combines" in func["description"].lower()


@pytest.mark.asyncio
async def test_generate_with_tools_tool_execution_error():
    await global_db.execute(
        "INSERT INTO agents (name, system_prompt, is_active) VALUES (?, ?, ?)",
        ("Error Bot", "Eres un asistente.", 1),
    )
    await global_db.commit()

    engine = InferenceEngine()
    engine._llm._available = True

    order_cap = OrderState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()
    _original_execute = order_cap.execute_tool

    async def failing_execute_tool(name, args, phone, tool_call_id, config):
        if name == "order_add":
            raise RuntimeError("DB connection lost")
        return await _original_execute(name, args, phone, tool_call_id, config)

    order_cap.execute_tool = failing_execute_tool

    tc = _make_tool_call("tc_err", "order_add", {"item_key": "completo_normal", "qty": 1})
    tool_response = _make_tool_response([tc])
    text_response = _make_text_response("Hubo un error procesando tu pedido.")

    call_count = 0

    async def mock_chat_completion(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return tool_response
        return text_response

    with patch.object(engine._llm, "chat_completion", side_effect=mock_chat_completion), \
         patch.object(engine._llm, "get_client", return_value=MagicMock()):
        text, _escalated, trace = await engine.generate(
            "agrega un completo", capabilities=[order_cap], phone="+56910000001",
        )

    assert "error" in text.lower() or "pedido" in text.lower()
    tools_executed = json.loads(trace["tools_executed"])
    assert len(tools_executed) == 1
    assert tools_executed[0]["result"]["success"] is False

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.capabilities.cart import CartCapability as CartState
from core.inference import (
    InferenceEngine,
    _guess_capability,
    _looks_like_leaked_tool_call,
    _try_extract_synthetic_tool_call,
)


def _make_tool_call(tc_id: str, name: str, args: dict) -> MagicMock:
    tc = MagicMock()
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _make_tool_response(tool_calls: list[MagicMock], content: str = "") -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 100
    resp.usage.completion_tokens = 50
    return resp


def _make_text_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 50
    resp.usage.completion_tokens = 20
    return resp


def test_looks_like_leaked_tool_call_positive():
    assert _looks_like_leaked_tool_call('{"type": "function", "function": {"name": "cart_add", "parameters": {"item_key": "item_a", "qty": 1}}}')
    assert _looks_like_leaked_tool_call('{"name": "cart_add", "arguments": {"item_key": "item_a"}}')
    assert _looks_like_leaked_tool_call('{"tool_calls": [{"function": {"name": "cart_add"}}]}')


def test_looks_like_leaked_tool_call_negative():
    assert not _looks_like_leaked_tool_call("Hola, te agrego 2 items a tu carrito.")
    assert not _looks_like_leaked_tool_call("")
    assert not _looks_like_leaked_tool_call(None)
    assert not _looks_like_leaked_tool_call("El precio es $3.700")
    assert not _looks_like_leaked_tool_call('{ "summary": "cliente pidio item" }')


def test_guess_capability():
    assert _guess_capability('{"name": "cart_add"}') == "cart"
    assert _guess_capability('{"name": "appointment_add"}') == "appointment"
    assert _guess_capability('{"name": "membership_activate"}') == "membership"
    assert _guess_capability('{"name": "lead_update_field"}') == "lead"
    assert _guess_capability("random text") == "unknown"


def test_try_extract_synthetic_tool_call():
    known = {"cart_add", "cart_remove", "escalate_to_human"}
    text = '{"type": "function", "function": {"name": "cart_add", "parameters": {"item_key": "item_a", "qty": 1}}}'
    result = _try_extract_synthetic_tool_call(text, known)
    assert result is not None
    assert result["name"] == "cart_add"
    assert result["args"]["item_key"] == "item_a"
    assert result["args"]["qty"] == 1
    assert result["id"].startswith("synthetic_")


def test_try_extract_synthetic_tool_call_unknown_name():
    known = {"cart_add"}
    text = '{"name": "unknown_tool", "arguments": {}}'
    result = _try_extract_synthetic_tool_call(text, known)
    assert result is None


def test_try_extract_synthetic_tool_call_malformed():
    known = {"cart_add"}
    assert _try_extract_synthetic_tool_call("not json at all", known) is None
    assert _try_extract_synthetic_tool_call("{broken json", known) is None
    assert _try_extract_synthetic_tool_call("{}", known) is None


@pytest.mark.asyncio
async def test_tool_discipline_instruction_in_system_prompt():
    engine = InferenceEngine()
    engine._llm._available = True
    engine._llm.get_client = MagicMock(return_value=MagicMock())
    engine._load_agent = AsyncMock(return_value=None)

    order_cap = CartState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()

    leaked_json = '{"type": "function", "function": {"name": "cart_add", "parameters": {"item_key": "item_a", "qty": 1}}}'
    text_resp = _make_text_response(leaked_json)

    retry_tc = _make_tool_call("retry_tc_1", "cart_add", {"item_key": "item_a", "qty": 1})
    retry_resp = _make_tool_response([retry_tc])

    final_resp = _make_text_response("Te agregue un item.")

    call_count = 0

    async def mock_chat_completion(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return text_resp
        if call_count == 2:
            last_msg = messages[-1]
            assert "tool_calls" in last_msg["content"].lower() or "DISCIPLINA" in str(messages[0]["content"])
            return retry_resp
        return final_resp

    with patch.object(engine._llm, "chat_completion", side_effect=mock_chat_completion), patch.object(
        engine._llm, "get_client", return_value=MagicMock()
    ):
        result = await engine.generate(
            "Quiero un item",
            capabilities=[order_cap],
            phone="+56910000001",
        )

    assert result[0] == "Te agregue un item."
    assert not result[1]


@pytest.mark.asyncio
async def test_leaked_json_tool_call_retry():
    engine = InferenceEngine()
    engine._llm._available = True
    engine._load_agent = AsyncMock(return_value=None)

    order_cap = CartState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()

    leaked_json = '{"type": "function", "function": {"name": "cart_add", "parameters": {"item_key": "item_a", "qty": 1}}}'
    text_resp = _make_text_response(leaked_json)

    retry_tc = _make_tool_call("retry_tc_1", "cart_add", {"item_key": "item_a", "qty": 1})
    retry_resp = _make_tool_response([retry_tc])

    final_resp = _make_text_response("Te agregue un item.")

    call_count = 0

    async def mock_chat_completion(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return text_resp
        if call_count == 2:
            return retry_resp
        return final_resp

    with patch.object(engine._llm, "chat_completion", side_effect=mock_chat_completion), patch.object(
        engine._llm, "get_client", return_value=MagicMock()
    ):
        text, escalated, _trace = await engine.generate(
            "Quiero un item",
            capabilities=[order_cap],
            phone="+56910000001",
        )

    assert "item" in text.lower() or "agreg" in text.lower()
    assert not escalated


@pytest.mark.asyncio
async def test_leaked_json_synthetic_fallback():
    engine = InferenceEngine()
    engine._llm._available = True
    engine._load_agent = AsyncMock(return_value=None)

    order_cap = CartState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()

    leaked_json = '{"type": "function", "function": {"name": "cart_add", "parameters": {"item_key": "item_a", "qty": 1}}}'
    text_resp = _make_text_response(leaked_json)

    retry_resp = _make_text_response(leaked_json)

    final_resp = _make_text_response("Listo, agregue tu item.")

    call_count = 0

    async def mock_chat_completion(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return text_resp
        if call_count == 2:
            return retry_resp
        return final_resp

    with patch.object(engine._llm, "chat_completion", side_effect=mock_chat_completion), patch.object(
        engine._llm, "get_client", return_value=MagicMock()
    ):
        text, escalated, trace = await engine.generate(
            "Quiero un item",
            capabilities=[order_cap],
            phone="+56910000001",
        )

    assert "listo" in text.lower() or "agreg" in text.lower()
    assert not escalated
    tools_executed = json.loads(trace["tools_executed"]) if trace["tools_executed"] else []
    assert any(te["tool"] == "cart_add" for te in tools_executed)


@pytest.mark.asyncio
async def test_legitimate_text_not_mistaken_for_leak():
    engine = InferenceEngine()
    engine._llm._available = True
    engine._load_agent = AsyncMock(return_value=None)

    order_cap = CartState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()

    legit_text = "Hola! Nuestro catalogo tiene items desde $3.700. Quieres algo?"
    text_resp = _make_text_response(legit_text)

    with patch.object(engine._llm, "chat_completion", return_value=text_resp), patch.object(
        engine._llm, "get_client", return_value=MagicMock()
    ):
        text, escalated, _trace = await engine.generate(
            "Que tienen?",
            capabilities=[order_cap],
            phone="+56910000001",
        )

    assert "item" in text.lower() or "catalogo" in text.lower() or "$3.700" in text
    assert not escalated


@pytest.mark.asyncio
async def test_leaked_json_final_output_escalates():
    engine = InferenceEngine()
    engine._llm._available = True
    engine._load_agent = AsyncMock(return_value=None)

    order_cap = CartState()
    order_cap._ensure_loaded = AsyncMock()
    order_cap._persist = AsyncMock()

    leaked_json = '{"type": "function", "function": {"name": "cart_add", "parameters": {"item_key": "item_a", "qty": 1}}}'

    text_resp = _make_text_response(leaked_json)

    call_count = 0

    async def mock_chat_completion(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return text_resp
        return _make_text_response(leaked_json)

    with patch.object(engine._llm, "chat_completion", side_effect=mock_chat_completion), patch.object(
        engine._llm, "get_client", return_value=MagicMock()
    ):
        _text, escalated, trace = await engine.generate(
            "Quiero un item",
            capabilities=[order_cap],
            phone="+56910000001",
        )

    assert escalated is True
    assert trace.get("escalation_reason") == "leaked_json_reached_output" or escalated


def test_sanitize_llm_output_unmodified():
    from core.security import sanitize_llm_output
    leaked = '{"type": "function", "function": {"name": "cart_add"}}'
    result = sanitize_llm_output(leaked)
    assert "cart_add" in result
    assert result.startswith("{")

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from core.turn_builder import BufferedMessage, TurnBuilder


@pytest.mark.asyncio
async def test_single_message_fires_after_debounce():
    builder = TurnBuilder()
    builder.debounce_seconds = 0.1

    process_turn_mock = AsyncMock()
    builder.set_process_turn_fn(process_turn_mock)

    await builder.debounce("+5691111", "Hola", "corr1", 1, session_id="sess-1")
    assert builder.get_buffer_size("+5691111") == 1
    await asyncio.sleep(0.3)
    process_turn_mock.assert_called_once()
    call_args = process_turn_mock.call_args
    assert call_args[0][0] == "+5691111"
    assert call_args[0][1] == "[1] Hola"
    assert call_args[0][2] == "corr1"
    assert call_args[0][3] == [1]
    assert call_args[0][4] == "sess-1"


@pytest.mark.asyncio
async def test_burst_consolidates():
    builder = TurnBuilder()
    builder.debounce_seconds = 0.2

    process_turn_mock = AsyncMock()
    builder.set_process_turn_fn(process_turn_mock)

    await builder.debounce("+5692222", "Hola", "c1", 1, session_id="sess-2")
    await builder.debounce("+5692222", "Quiero un completo", "c1", 2, session_id="sess-2")
    await builder.debounce("+5692222", "Con todo", "c1", 3, session_id="sess-2")
    assert builder.get_buffer_size("+5692222") == 3
    await asyncio.sleep(0.5)
    process_turn_mock.assert_called_once()
    call_args = process_turn_mock.call_args
    assert call_args[0][0] == "+5692222"
    assert call_args[0][1] == "[1] Hola\n\n[2] Quiero un completo\n\n[3] Con todo"
    assert call_args[0][3] == [1, 2, 3]
    assert call_args[0][4] == "sess-2"


@pytest.mark.asyncio
async def test_consolidation_format():
    builder = TurnBuilder()
    msgs = [
        BufferedMessage(text="Hola", correlation_id="c1", message_id=1, session_id="s1", received_at=time.monotonic()),
        BufferedMessage(text="Quiero un completo", correlation_id="c1", message_id=2, session_id="s1", received_at=time.monotonic()),
        BufferedMessage(text="Con todo", correlation_id="c1", message_id=3, session_id="s1", received_at=time.monotonic()),
    ]
    consolidated, corr_id, msg_ids, session_id = builder._consolidate(msgs)
    assert consolidated == "[1] Hola\n\n[2] Quiero un completo\n\n[3] Con todo"
    assert corr_id == "c1"
    assert msg_ids == [1, 2, 3]
    assert session_id == "s1"


@pytest.mark.asyncio
async def test_consolidation_no_session_id():
    builder = TurnBuilder()
    msgs = [
        BufferedMessage(text="Hola", correlation_id="c1", message_id=1, received_at=time.monotonic()),
    ]
    _consolidated, _corr_id, _msg_ids, session_id = builder._consolidate(msgs)
    assert session_id is None


@pytest.mark.asyncio
async def test_timer_resets_on_new_message():
    builder = TurnBuilder()
    builder.debounce_seconds = 0.2

    process_turn_mock = AsyncMock()
    builder.set_process_turn_fn(process_turn_mock)

    await builder.debounce("+5693333", "Msg1", "c1", 1, session_id="s1")
    await asyncio.sleep(0.1)
    assert builder.get_buffer_size("+5693333") == 1
    await builder.debounce("+5693333", "Msg2", "c1", 2, session_id="s1")
    await asyncio.sleep(0.1)
    assert process_turn_mock.call_count == 0
    await asyncio.sleep(0.3)
    assert process_turn_mock.call_count == 1
    call_args = process_turn_mock.call_args
    assert "[1] Msg1" in call_args[0][1]
    assert "[2] Msg2" in call_args[0][1]


@pytest.mark.asyncio
async def test_flush_immediate():
    builder = TurnBuilder()
    builder.debounce_seconds = 10.0

    process_turn_mock = AsyncMock()
    builder.set_process_turn_fn(process_turn_mock)

    await builder.debounce("+5694444", "Hola", "c1", 1, session_id="s1")
    await builder.debounce("+5694444", "Chao", "c1", 2, session_id="s1")
    assert builder.get_buffer_size("+5694444") == 2
    await builder.flush("+5694444")
    process_turn_mock.assert_called_once()
    assert builder.get_buffer_size("+5694444") == 0


@pytest.mark.asyncio
async def test_empty_buffer_noop():
    builder = TurnBuilder()
    builder.debounce_seconds = 10.0

    process_turn_mock = AsyncMock()
    builder.set_process_turn_fn(process_turn_mock)

    await builder.flush("+5695555")
    process_turn_mock.assert_not_called()


@pytest.mark.asyncio
async def test_different_phones_independent():
    builder = TurnBuilder()
    builder.debounce_seconds = 0.2

    process_turn_mock = AsyncMock()
    builder.set_process_turn_fn(process_turn_mock)

    await builder.debounce("+5696666", "Msg phone 6", "c6", 1, session_id="s6")
    await builder.debounce("+5697777", "Msg phone 7", "c7", 2, session_id="s7")
    await asyncio.sleep(0.5)
    assert process_turn_mock.call_count == 2
    calls = [c[0][0] for c in process_turn_mock.call_args_list]
    assert "+5696666" in calls
    assert "+5697777" in calls


@pytest.mark.asyncio
async def test_debounce_without_session_id():
    builder = TurnBuilder()
    builder.debounce_seconds = 0.1

    process_turn_mock = AsyncMock()
    builder.set_process_turn_fn(process_turn_mock)

    await builder.debounce("+5698888", "Hola", "c1", 1)
    await asyncio.sleep(0.3)
    call_args = process_turn_mock.call_args
    assert call_args[0][4] is None

import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from core.inference import _normalize_roles
from core.turn_builder import TurnBuilder
from db.database import db
from db.models import Turn


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    await db.execute("DELETE FROM turns")
    await db.execute("DELETE FROM messages")
    await db.execute("DELETE FROM conversation_memory")
    await db.execute("DELETE FROM escalation_events")
    await db.execute("DELETE FROM agent_decisions")
    await db.execute("DELETE FROM carts")
    await db.execute("UPDATE conversations SET current_session_id = NULL")
    await db.execute("DELETE FROM sessions")
    await db.execute("DELETE FROM conversations")
    await db.execute("DELETE FROM agents")
    await db.execute("INSERT INTO agents (id, name, system_prompt) VALUES ($1, $2, $3)", 1, 'Default Agent', 'Prompt')
    await db.execute("DELETE FROM agent_capabilities")
    await db.execute("INSERT INTO agent_capabilities (agent_id, capability_name, is_active, config_json) VALUES ($1, $2, $3, $4)", 1, 'cart', True, '{}')


@pytest.mark.asyncio
async def test_burst_three_messages_single_llm_call():
    builder = TurnBuilder()
    builder.debounce_seconds = 0.1

    phone = "+569E2E0001"
    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, $2, $3)", phone, 'BOT_ACTIVE', 1)

    process_turn_mock = AsyncMock()
    builder.set_process_turn_fn(process_turn_mock)

    await builder.debounce(phone, "Hola", "corr1", 1, session_id="e2e-sess-1")
    await builder.debounce(phone, "Quiero un completo", "corr1", 2, session_id="e2e-sess-1")
    await builder.debounce(phone, "Con todo", "corr1", 3, session_id="e2e-sess-1")

    await asyncio.sleep(0.4)

    process_turn_mock.assert_called_once()
    call_args = process_turn_mock.call_args
    consolidated_text = call_args[0][1]
    assert "[1] Hola" in consolidated_text
    assert "[2] Quiero un completo" in consolidated_text
    assert "[3] Con todo" in consolidated_text


@pytest.mark.asyncio
async def test_turn_based_history_no_400():
    phone = "+569E2E0002"
    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, $2, $3)", phone, 'BOT_ACTIVE', 1)

    for i in range(5):
        await db.insert_turn(Turn(
            phone=phone,
            user_text=f"User message {i}",
            assistant_text=f"Bot reply {i}",
        ))

    from core.memory import memory_manager
    history = await memory_manager.build_context(phone, agent_id=1)

    non_system = [m for m in history if m["role"] != "system"]
    for i in range(0, len(non_system) - 1):
        assert non_system[i]["role"] != non_system[i + 1]["role"], \
            f"Consecutive same roles at index {i}: {non_system[i]['role']}"


@pytest.mark.asyncio
async def test_normalize_roles_catches_edge_case():
    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "system", "content": "Capability context"},
        {"role": "user", "content": "Msg 1"},
        {"role": "user", "content": "Msg 2"},
        {"role": "assistant", "content": "Reply"},
        {"role": "assistant", "content": "Extra reply"},
        {"role": "user", "content": "Msg 3"},
    ]
    normalized = _normalize_roles(messages)

    roles = [m["role"] for m in normalized]
    for i in range(len(roles) - 1):
        if roles[i] == "system":
            continue
        assert roles[i] != roles[i + 1], f"Consecutive same roles: {roles[i]} at index {i}"

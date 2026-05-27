from datetime import UTC, datetime, timedelta

import pytest

from core.sessions import session_manager
from db.database import db


@pytest.mark.asyncio
async def test_get_or_create_session_new():
    phone = "+56911112222"
    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", phone)

    sid = await session_manager.get_or_create_session(phone)
    assert sid is not None

    conv = await db.get_conversation(phone)
    assert conv.current_session_id == sid

    session = await db.get_active_session(phone)
    assert session.id == sid


@pytest.mark.asyncio
async def test_get_or_create_session_existing_active():
    phone = "+56933334444"
    await db.execute("INSERT INTO conversations (phone, state, agent_id, last_message_at) VALUES ($1, 'BOT_ACTIVE', 1, NOW())", phone)

    sid1 = await session_manager.get_or_create_session(phone)
    sid2 = await session_manager.get_or_create_session(phone)

    assert sid1 == sid2


@pytest.mark.asyncio
async def test_get_or_create_session_timeout():
    phone = "+56955556666"
    five_hours_ago = datetime.now(UTC) - timedelta(hours=5)

    await db.execute("INSERT INTO conversations (phone, state, agent_id, last_message_at) VALUES ($1, 'BOT_ACTIVE', 1, $2)", phone, five_hours_ago)

    sid1 = await session_manager.get_or_create_session(phone)

    await db.execute("UPDATE conversations SET last_message_at=$1 WHERE phone=$2", five_hours_ago, phone)

    sid2 = await session_manager.get_or_create_session(phone)

    assert sid1 != sid2

    conv = await db.get_conversation(phone)
    assert conv.state == "BOT_ACTIVE"
    assert conv.current_session_id == sid2


@pytest.mark.asyncio
async def test_increment_message_count():
    phone = "+56977778888"
    await db.execute("INSERT INTO conversations (phone, agent_id) VALUES ($1, 1)", phone)

    sid = await session_manager.get_or_create_session(phone)
    await db.increment_session_message_count(sid)
    await db.increment_session_message_count(sid)

    session = await db.get_active_session(phone)
    assert session.message_count == 2


@pytest.mark.asyncio
async def test_close_session_manual():
    phone = "+56999990000"
    await db.execute("INSERT INTO conversations (phone, agent_id) VALUES ($1, 1)", phone)

    sid = await session_manager.get_or_create_session(phone)
    await db.close_session(sid, reason="manual", summary="Test summary")

    session = await db.get_active_session(phone)
    assert session is None

    row = await db.fetchone("SELECT * FROM sessions WHERE id=$1", sid)
    assert row["end_reason"] == "manual"
    assert row["summary"] == "Test summary"
    assert row["ended_at"] is not None


@pytest.mark.asyncio
async def test_no_timeout_does_not_create_new_session():
    phone = "+56911114444"
    await db.execute("INSERT INTO conversations (phone, state, agent_id, last_message_at) VALUES ($1, 'BOT_ACTIVE', 1, NOW())", phone)

    sid1 = await session_manager.get_or_create_session(phone)

    await db.execute("UPDATE conversations SET last_message_at=NOW() WHERE phone=$1", phone)

    sid2 = await session_manager.get_or_create_session(phone)

    assert sid1 == sid2


@pytest.mark.asyncio
async def test_timeout_preserves_escalated_state():
    phone = "+56955551111"
    five_hours_ago = datetime.now(UTC) - timedelta(hours=5)

    await db.execute("INSERT INTO conversations (phone, state, agent_id, last_message_at) VALUES ($1, 'PENDING_APPROVAL', 1, $2)", phone, five_hours_ago)

    sid1 = await session_manager.get_or_create_session(phone)

    await db.execute("UPDATE conversations SET last_message_at=$1 WHERE phone=$2", five_hours_ago, phone)

    sid2 = await session_manager.get_or_create_session(phone)

    assert sid1 != sid2
    conv = await db.get_conversation(phone)
    assert conv.state == "PENDING_APPROVAL"
    assert conv.current_session_id == sid2

import pytest
import pytest_asyncio
import os
import asyncio
from datetime import datetime, timedelta, timezone
from core.sessions import session_manager, SESSION_TIMEOUT_HOURS
from db.database import db, init_db, close_db

@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_session_db():
    from core.config import settings
    import random
    suffix = random.randint(1000, 9999)
    test_db = f"./tests/data/test_sessions_{suffix}.db"
    settings.DB_PATH = test_db
    
    os.makedirs("./tests/data", exist_ok=True)
    if os.path.exists(test_db):
        os.remove(test_db)
        
    await init_db()
    conn = await db._get_conn()
    await conn.execute("PRAGMA foreign_keys=OFF")
    
    with open("db/schema.sql", "r") as f:
        schema = f.read()
        await conn.executescript(schema)
        await db.commit()
    
    await conn.execute("PRAGMA foreign_keys=ON")
    
    await conn.execute("PRAGMA foreign_keys=ON")
    
    yield
    await close_db()

@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    await db.execute("UPDATE conversations SET current_session_id = NULL")
    await db.execute("DELETE FROM agent_decisions")
    await db.execute("DELETE FROM messages")
    await db.execute("DELETE FROM sessions")
    await db.execute("DELETE FROM conversation_memory")
    await db.execute("DELETE FROM escalation_events")
    await db.execute("DELETE FROM conversations")
    await db.execute("DELETE FROM agents")
    await db.execute("INSERT OR IGNORE INTO agents (id, name, system_prompt) VALUES (1, 'Test Agent', 'Prompt')")
    await db.commit()

@pytest.mark.asyncio
async def test_get_or_create_session_new():
    phone = "+56911112222"
    # Crear conversación previa
    await db.execute("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", (phone,))
    await db.commit()
    
    sid = await session_manager.get_or_create_session(phone)
    assert sid is not None
    
    # Verificar en DB
    conv = await db.get_conversation(phone)
    assert conv.current_session_id == sid
    
    session = await db.get_active_session(phone)
    assert session.id == sid

@pytest.mark.asyncio
async def test_get_or_create_session_existing_active():
    phone = "+56933334444"
    await db.execute("INSERT INTO conversations (phone, state, agent_id, last_message_at) VALUES (?, 'BOT_ACTIVE', 1, CURRENT_TIMESTAMP)", (phone,))
    await db.commit()
    
    sid1 = await session_manager.get_or_create_session(phone)
    sid2 = await session_manager.get_or_create_session(phone)
    
    assert sid1 == sid2

@pytest.mark.asyncio
async def test_get_or_create_session_timeout():
    phone = "+56955556666"
    # Simular mensaje hace 5 horas
    five_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
    
    await db.execute("INSERT INTO conversations (phone, state, agent_id, last_message_at) VALUES (?, 'PENDING_APPROVAL', 1, ?)", (phone, five_hours_ago))
    await db.commit()
    
    sid1 = await session_manager.get_or_create_session(phone)
    
    # Simular que el mensaje de sid1 fue hace 5 horas
    await db.execute("UPDATE conversations SET last_message_at=? WHERE phone=?", (five_hours_ago, phone))
    await db.commit()
    
    sid2 = await session_manager.get_or_create_session(phone)
    
    assert sid1 != sid2
    
    # Verificar que el estado volvió a BOT_ACTIVE
    conv = await db.get_conversation(phone)
    assert conv.state == "BOT_ACTIVE"
    assert conv.current_session_id == sid2

@pytest.mark.asyncio
async def test_increment_message_count():
    phone = "+56977778888"
    await db.execute("INSERT INTO conversations (phone, agent_id) VALUES (?, 1)", (phone,))
    await db.commit()
    
    sid = await session_manager.get_or_create_session(phone)
    await db.increment_session_message_count(sid)
    await db.increment_session_message_count(sid)
    
    session = await db.get_active_session(phone)
    assert session.message_count == 2

@pytest.mark.asyncio
async def test_close_session_manual():
    phone = "+56999990000"
    await db.execute("INSERT INTO conversations (phone, agent_id) VALUES (?, 1)", (phone,))
    await db.commit()
    
    sid = await session_manager.get_or_create_session(phone)
    await db.close_session(sid, reason="manual", summary="Test summary")
    
    session = await db.get_active_session(phone)
    assert session is None # Ya no hay sesión activa
    
    # Verificar en tabla sessions
    row = await db.fetchone("SELECT * FROM sessions WHERE id=?", (sid,))
    assert row["end_reason"] == "manual"
    assert row["summary"] == "Test summary"
    assert row["ended_at"] is not None

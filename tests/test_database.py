import os
import sqlite3

import aiosqlite
import pytest
import pytest_asyncio

from db.database import Database

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")


@pytest_asyncio.fixture
async def db():
    test_db_path = "/tmp/hermes_test/test_unit.db"
    os.makedirs("/tmp/hermes_test", exist_ok=True)
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

    with open(SCHEMA_PATH) as f:
        schema = f.read()

    sync_conn = sqlite3.connect(test_db_path)
    sync_conn.executescript(schema)
    sync_conn.close()

    conn = await aiosqlite.connect(test_db_path)
    conn.row_factory = aiosqlite.Row

    database = Database()
    database._conn = conn

    yield database

    await conn.close()
    if os.path.exists(test_db_path):
        os.remove(test_db_path)


@pytest.mark.asyncio
async def test_execute_transaction_commit(db):
    await db.execute("INSERT INTO agents (id, name, system_prompt) VALUES (1, 'Test', 'Prompt')")
    await db.commit()
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", ("+5691234",)),
    ])
    row = await db.fetchone("SELECT state FROM conversations WHERE phone=?", ("+5691234",))
    assert row is not None
    assert row["state"] == "BOT_ACTIVE"


@pytest.mark.asyncio
async def test_execute_transaction_rollback(db):
    await db.execute("INSERT INTO agents (id, name, system_prompt) VALUES (1, 'Test', 'Prompt')")
    await db.commit()
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", ("+5699999",)),
    ])
    with pytest.raises(Exception, match="UNIQUE constraint"):
        await db.execute_transaction([
            ("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", ("+5699999",)),
        ])
    row = await db.fetchone("SELECT COUNT(*) as cnt FROM conversations WHERE phone=?", ("+5699999",))
    assert row["cnt"] == 1


@pytest.mark.asyncio
async def test_fetchall(db):
    await db.execute("INSERT INTO agents (id, name, system_prompt) VALUES (1, 'Test', 'Prompt')")
    await db.commit()
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", ("+5691111",)),
        ("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'HUMAN_ONLY', 1)", ("+5692222",)),
    ])
    rows = await db.fetchall("SELECT phone FROM conversations ORDER BY phone")
    assert len(rows) == 2
    assert rows[0]["phone"] == "+5691111"


@pytest.mark.asyncio
async def test_update_conversation_state(db):
    await db.execute("INSERT INTO agents (id, name, system_prompt) VALUES (1, 'Test', 'Prompt')")
    await db.commit()
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", ("+5695555",)),
    ])
    await db.update_conversation_state("+5695555", "PENDING_APPROVAL", requires_human_review=True)
    row = await db.fetchone("SELECT state, requires_human_review FROM conversations WHERE phone=?", ("+5695555",))
    assert row["state"] == "PENDING_APPROVAL"
    assert row["requires_human_review"] == 1


@pytest.mark.asyncio
async def test_reset_conversation_session(db):
    await db.execute("INSERT INTO agents (id, name, system_prompt) VALUES (1, 'Test', 'Prompt')")
    await db.commit()
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id, current_session_id, requires_human_review) VALUES (?, 'PENDING_APPROVAL', 1, 'sess-1', 1)", ("+5696666",)),
    ])
    await db.reset_conversation_session("+5696666")
    row = await db.fetchone("SELECT current_session_id, state, requires_human_review FROM conversations WHERE phone=?", ("+5696666",))
    assert row["current_session_id"] is None
    assert row["state"] == "BOT_ACTIVE"
    assert row["requires_human_review"] == 0


@pytest.mark.asyncio
async def test_set_conversation_agent(db):
    await db.execute("INSERT INTO agents (id, name, system_prompt) VALUES (1, 'Agent1', 'P1')")
    await db.execute("INSERT INTO agents (id, name, system_prompt) VALUES (2, 'Agent2', 'P2')")
    await db.commit()
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", ("+5697777",)),
    ])
    await db.set_conversation_agent("+5697777", 2)
    row = await db.fetchone("SELECT agent_id FROM conversations WHERE phone=?", ("+5697777",))
    assert row["agent_id"] == 2


@pytest.mark.asyncio
async def test_load_menu_items_empty(db):
    items = await db.load_menu_items()
    assert items == []


@pytest.mark.asyncio
async def test_upsert_and_load_menu_items(db):
    await db.upsert_menu_item("test_item", "Test Item", 1000, category="test", sort_order=1)
    await db.upsert_menu_item("test_item2", "Test Item 2", 2000, category="test", sort_order=2)
    items = await db.load_menu_items()
    assert len(items) == 2
    assert items[0]["key"] == "test_item"
    assert items[0]["price"] == 1000


@pytest.mark.asyncio
async def test_upsert_menu_item_updates_existing(db):
    await db.upsert_menu_item("test_item", "Original", 1000)
    await db.upsert_menu_item("test_item", "Updated", 1500)
    items = await db.load_menu_items()
    assert len(items) == 1
    assert items[0]["name"] == "Updated"
    assert items[0]["price"] == 1500

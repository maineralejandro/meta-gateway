import pytest
import pytest_asyncio
import sqlite3
import aiosqlite
from httpx import AsyncClient, ASGITransport
from db.database import Database, init_db, close_db, get_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    phone TEXT PRIMARY KEY,
    contact_name TEXT,
    state TEXT DEFAULT 'BOT_ACTIVE' CHECK(state IN ('BOT_ACTIVE','PENDING_APPROVAL','HUMAN_ONLY')),
    last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    requires_human_review INTEGER DEFAULT 0,
    unread_count INTEGER DEFAULT 0,
    sentiment_score REAL,
    confidence REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    source TEXT NOT NULL CHECK(source IN ('bot','human','customer')),
    text TEXT,
    media_type TEXT,
    media_url TEXT,
    meta_message_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);
CREATE TABLE IF NOT EXISTS escalation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason TEXT,
    sentiment_score REAL,
    confidence REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);
"""


@pytest_asyncio.fixture
async def db():
    test_db_path = "/tmp/hermes_test/test_unit.db"
    os.makedirs("/tmp/hermes_test", exist_ok=True)
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

    conn = await aiosqlite.connect(test_db_path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)

    database = Database.__new__(Database)
    database._conn = conn

    yield database

    await conn.close()
    if os.path.exists(test_db_path):
        os.remove(test_db_path)


import os


@pytest.mark.asyncio
async def test_execute_transaction_commit(db):
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state) VALUES (?, 'BOT_ACTIVE')", ("+5691234",)),
    ])
    row = await db.fetchone("SELECT state FROM conversations WHERE phone=?", ("+5691234",))
    assert row is not None
    assert row["state"] == "BOT_ACTIVE"


@pytest.mark.asyncio
async def test_execute_transaction_rollback(db):
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state) VALUES (?, 'BOT_ACTIVE')", ("+5699999",)),
    ])
    with pytest.raises(Exception):
        await db.execute_transaction([
            ("INSERT INTO conversations (phone, state) VALUES (?, 'BOT_ACTIVE')", ("+5699999",)),
        ])
    row = await db.fetchone("SELECT COUNT(*) as cnt FROM conversations WHERE phone=?", ("+5699999",))
    assert row["cnt"] == 1


@pytest.mark.asyncio
async def test_fetchall(db):
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state) VALUES (?, 'BOT_ACTIVE')", ("+5691111",)),
        ("INSERT INTO conversations (phone, state) VALUES (?, 'HUMAN_ONLY')", ("+5692222",)),
    ])
    rows = await db.fetchall("SELECT phone FROM conversations ORDER BY phone")
    assert len(rows) == 2
    assert rows[0]["phone"] == "+5691111"

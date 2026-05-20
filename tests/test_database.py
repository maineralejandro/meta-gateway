import asyncpg
import pytest
import pytest_asyncio

from db.database import Database


@pytest_asyncio.fixture
async def db():
    database = Database()
    yield database


@pytest.mark.asyncio
async def test_execute_transaction_commit(db):
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", ("+5691234",)),
    ])
    row = await db.fetchone("SELECT state FROM conversations WHERE phone=$1", "+5691234")
    assert row is not None
    assert row["state"] == "BOT_ACTIVE"


@pytest.mark.asyncio
async def test_execute_transaction_rollback(db):
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", ("+5699999",)),
    ])
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await db.execute_transaction([
            ("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", ("+5699999",)),
        ])
    row = await db.fetchone("SELECT COUNT(*) as cnt FROM conversations WHERE phone=$1", "+5699999")
    assert row["cnt"] == 1


@pytest.mark.asyncio
async def test_fetchall(db):
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", ("+5691111",)),
        ("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'HUMAN_ONLY', 1)", ("+5692222",)),
    ])
    rows = await db.fetchall("SELECT phone FROM conversations ORDER BY phone")
    assert len(rows) == 2
    assert rows[0]["phone"] == "+5691111"


@pytest.mark.asyncio
async def test_update_conversation_state(db):
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", ("+5695555",)),
    ])
    await db.update_conversation_state("+5695555", "PENDING_APPROVAL", requires_human_review=True)
    row = await db.fetchone("SELECT state, requires_human_review FROM conversations WHERE phone=$1", "+5695555")
    assert row["state"] == "PENDING_APPROVAL"
    assert row["requires_human_review"] is True


@pytest.mark.asyncio
async def test_reset_conversation_session(db):
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id, requires_human_review) VALUES ($1, 'PENDING_APPROVAL', 1, TRUE)", ("+5696666",)),
        ("INSERT INTO sessions (id, phone) VALUES ($1, $2)", ("sess-1", "+5696666")),
        ("UPDATE conversations SET current_session_id = $1 WHERE phone = $2", ("sess-1", "+5696666")),
    ])
    await db.reset_conversation_session("+5696666")
    row = await db.fetchone("SELECT current_session_id, state, requires_human_review FROM conversations WHERE phone=$1", "+5696666")
    assert row["current_session_id"] is None
    assert row["state"] == "BOT_ACTIVE"
    assert row["requires_human_review"] is False


@pytest.mark.asyncio
async def test_set_conversation_agent(db):
    await db.execute("INSERT INTO agents (id, name, system_prompt, escalation_marker, fallback_responses, is_active) VALUES ($1, $2, $3, $4, $5, $6)", 2, "Agent2", "P2", "ESCALATE", "{}", True)
    await db.execute_transaction([
        ("INSERT INTO conversations (phone, state, agent_id) VALUES ($1, 'BOT_ACTIVE', 1)", ("+5697777",)),
    ])
    await db.set_conversation_agent("+5697777", 2)
    row = await db.fetchone("SELECT agent_id FROM conversations WHERE phone=$1", "+5697777")
    assert row["agent_id"] == 2


@pytest.mark.asyncio
async def test_load_catalog_items_empty(db):
    items = await db.load_catalog_items()
    assert items == []


@pytest.mark.asyncio
async def test_upsert_and_load_catalog_items(db):
    await db.upsert_catalog_item("test_item", "Test Item", 1000, category="test", sort_order=1)
    await db.upsert_catalog_item("test_item2", "Test Item 2", 2000, category="test", sort_order=2)
    items = await db.load_catalog_items()
    assert len(items) == 2
    assert items[0]["key"] == "test_item"
    assert items[0]["price"] == 1000


@pytest.mark.asyncio
async def test_upsert_catalog_item_updates_existing(db):
    await db.upsert_catalog_item("test_item", "Original", 1000)
    await db.upsert_catalog_item("test_item", "Updated", 1500)
    items = await db.load_catalog_items()
    assert len(items) == 1
    assert items[0]["name"] == "Updated"
    assert items[0]["price"] == 1500

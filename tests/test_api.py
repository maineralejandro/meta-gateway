import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import sqlite3
import aiosqlite
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import app
from db.database import db as global_db

TEST_DB_PATH = "/tmp/hermes_test/test_api.db"


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    os.makedirs("/tmp/hermes_test", exist_ok=True)
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    from core.config import settings
    settings.DB_PATH = TEST_DB_PATH
    settings.DASHBOARD_TOKEN = "test_dashboard_token"

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
    await global_db._conn.execute("PRAGMA journal_mode=WAL")
    await global_db._conn.execute("PRAGMA foreign_keys=ON")
    await global_db._conn.execute(
        "INSERT INTO agents (id, name, system_prompt, is_active) VALUES (1, 'Default', '...', 1)"
    )
    await global_db._conn.commit()

    yield

    if global_db._conn:
        await global_db._conn.close()
        global_db._conn = None
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


AUTH_HEADERS = {"Authorization": "Bearer test_dashboard_token"}


@pytest.mark.asyncio
async def test_home_page():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/")
    assert res.status_code == 200
    assert "Hermes" in res.text


@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_webhook_verification_wrong_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/webhook/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "123"},
        )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_api_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/conversations")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_api_with_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/conversations", headers=AUTH_HEADERS)
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_conversations_state_update():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/conversations/state",
            json={"phone": "+5691234", "state": "HUMAN_ONLY"},
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["new_state"] == "HUMAN_ONLY"


@pytest.mark.asyncio
async def test_agents_crud():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create Agent
        res = await client.post(
            "/api/agents",
            json={
                "name": "Test Agent",
                "system_prompt": "You are a test agent.",
                "fallback_responses": '{"default": "test fallback"}'
            },
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        )
        assert res.status_code == 200
        agent_id = res.json()["id"]

        # 2. Get List
        res = await client.get("/api/agents", headers=AUTH_HEADERS)
        assert res.status_code == 200
        assert len(res.json()) >= 1

        # 3. Update
        res = await client.put(
            f"/api/agents/{agent_id}",
            json={"description": "Updated description"},
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        )
        assert res.status_code == 200
        assert res.json()["description"] == "Updated description"

        # 4. Activate
        res = await client.post(
            f"/api/agents/{agent_id}/activate",
            headers=AUTH_HEADERS
        )
        assert res.status_code == 200
        assert res.json()["status"] == "success"

@pytest.mark.asyncio
async def test_conversation_change_agent():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create an agent first
        res = await client.post(
            "/api/agents",
            json={"name": "A2", "system_prompt": "P2"},
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        )
        agent_id = res.json()["id"]

        # Change agent of a conversation
        res = await client.post(
            "/api/conversations/agent",
            json={"phone": "+5691234", "agent_id": agent_id},
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        )
        assert res.status_code == 200
        assert res.json()["agent_id"] == agent_id

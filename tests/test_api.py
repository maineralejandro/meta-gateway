import pytest
from httpx import ASGITransport, AsyncClient

AUTH_HEADERS = {"Authorization": "Bearer test_dashboard_token"}


@pytest.mark.asyncio
async def test_home_page():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/")
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_health_check():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert "status" in data


@pytest.mark.asyncio
async def test_webhook_verification_wrong_token():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/webhook/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "123"},
        )
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_api_requires_auth():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/conversations")
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_api_with_auth():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/conversations", headers=AUTH_HEADERS)
        assert res.status_code == 200
        assert res.json() == []


@pytest.mark.asyncio
async def test_conversations_state_update():
    from main import app
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
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
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

        res = await client.get("/api/agents", headers=AUTH_HEADERS)
        assert res.status_code == 200
        assert len(res.json()) >= 1

        res = await client.put(
            f"/api/agents/{agent_id}",
            json={"description": "Updated description"},
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        )
        assert res.status_code == 200
        assert res.json()["description"] == "Updated description"

        res = await client.post(
            f"/api/agents/{agent_id}/activate",
            headers=AUTH_HEADERS
        )
        assert res.status_code == 200
        assert res.json()["status"] == "success"


@pytest.mark.asyncio
async def test_conversation_change_agent():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/agents",
            json={"name": "A2", "system_prompt": "P2"},
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        )
        agent_id = res.json()["id"]

        res = await client.post(
            "/api/conversations/agent",
            json={"phone": "+5691234", "agent_id": agent_id},
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        )
        assert res.status_code == 200
        assert res.json()["agent_id"] == agent_id


@pytest.mark.asyncio
async def test_conversation_not_found_returns_404():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/conversations/+56999990000", headers=AUTH_HEADERS)
        assert res.status_code == 404
        assert res.json()["error"] == "not_found"

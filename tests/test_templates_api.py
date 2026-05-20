import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from httpx import ASGITransport, AsyncClient

from core.capabilities.appointment import AppointmentCapability
from core.capabilities.base import registry
from core.capabilities.cart import CartCapability
from core.capabilities.lead import LeadCapability
from core.capabilities.membership import MembershipCapability

AUTH = {"Authorization": "Bearer test_dashboard_token"}


@pytest.fixture(autouse=True)
def setup_registry():
    registry._capabilities.clear()
    registry._cache.clear()
    registry.register(CartCapability)
    registry.register(AppointmentCapability)
    registry.register(MembershipCapability)
    registry.register(LeadCapability)
    yield
    registry._capabilities.clear()
    registry._cache.clear()


@pytest.mark.asyncio
async def test_list_templates():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/templates", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4
        names = [t["name"] for t in data]
        assert "retail" in names
        assert "dentista" in names
        assert "gym" in names
        assert "inmobiliaria" in names


@pytest.mark.asyncio
async def test_get_template():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/templates/1", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "retail"
        assert "{{business_name}}" in data["system_prompt_template"]


@pytest.mark.asyncio
async def test_get_template_404():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/templates/999", headers=AUTH)
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_from_template():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/templates/from-template",
            json={"template_id": 1, "fields": {"business_name": "Sanguches Juan", "products": "items, acompanamientos"}},
            headers=AUTH,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] > 0
        assert data["capabilities_created"] == 1

        agent_resp = await client.get(f"/api/agents/{data['agent_id']}", headers=AUTH)
        assert agent_resp.status_code == 200
        agent = agent_resp.json()
        assert "Sanguches Juan" in agent["system_prompt"]

        caps_resp = await client.get(f"/api/agents/{data['agent_id']}/capabilities", headers=AUTH)
        assert caps_resp.status_code == 200
        caps = caps_resp.json()
        assert len(caps) == 1
        assert caps[0]["capability_name"] == "cart"


@pytest.mark.asyncio
async def test_create_from_template_dentist():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/templates/from-template",
            json={"template_id": 2, "fields": {"business_name": "Clinica Dr. Lopez"}},
            headers=AUTH,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["capabilities_created"] == 1

        caps_resp = await client.get(f"/api/agents/{data['agent_id']}/capabilities", headers=AUTH)
        caps = caps_resp.json()
        assert caps[0]["capability_name"] == "appointment"


@pytest.mark.asyncio
async def test_create_from_template_404():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/templates/from-template",
            json={"template_id": 999, "fields": {}},
            headers=AUTH,
        )
        assert resp.status_code == 404

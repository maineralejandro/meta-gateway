from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.capabilities.appointment import AppointmentCapability
from core.capabilities.base import registry
from core.capabilities.lead import LeadCapability
from core.capabilities.membership import MembershipCapability
from core.capabilities.order import OrderCapability
from db.database import get_db
from db.models import Agent, AgentCapability

AUTH_HEADERS = {"Authorization": "Bearer test_dashboard_token"}

_mock_db = MagicMock()
_mock_db.get_agent = AsyncMock(return_value=Agent(id=1, name="Test", system_prompt="test"))
_mock_db.get_agent_capabilities = AsyncMock(return_value=[])
_mock_db.upsert_agent_capability = AsyncMock(return_value=1)
_mock_db.delete_agent_capability = AsyncMock()


@pytest.fixture(autouse=True)
def setup_registry():
    if not registry.get_class("appointment"):
        registry.register(AppointmentCapability)
    if not registry.get_class("lead"):
        registry.register(LeadCapability)
    if not registry.get_class("membership"):
        registry.register(MembershipCapability)
    if not registry.get_class("order"):
        registry.register(OrderCapability)


@pytest.fixture
def client():
    from main import app
    app.dependency_overrides[get_db] = lambda: _mock_db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_mocks():
    _mock_db.get_agent = AsyncMock(return_value=Agent(id=1, name="Test", system_prompt="test"))
    _mock_db.get_agent_capabilities = AsyncMock(return_value=[])
    _mock_db.upsert_agent_capability = AsyncMock(return_value=1)
    _mock_db.delete_agent_capability = AsyncMock()
    yield


def test_list_capabilities(client):
    response = client.get("/api/capabilities", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    names = [c["name"] for c in data]
    assert "appointment" in names
    assert "lead" in names
    assert "membership" in names
    assert "order" in names
    for cap in data:
        assert "name" in cap
        assert "description" in cap
        assert "config_schema" in cap


def test_get_agent_capabilities_empty(client):
    _mock_db.get_agent_capabilities = AsyncMock(return_value=[])
    response = client.get("/api/agents/1/capabilities", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == []


def test_get_agent_capabilities(client):
    _mock_db.get_agent_capabilities = AsyncMock(return_value=[
        AgentCapability(id=1, agent_id=1, capability_name="appointment", is_active=1, config_json='{"slot_duration_minutes": 45}'),
    ])
    response = client.get("/api/agents/1/capabilities", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["capability_name"] == "appointment"
    assert data[0]["is_active"] == 1
    assert data[0]["config_json"] == '{"slot_duration_minutes": 45}'


def test_get_agent_capabilities_404(client):
    _mock_db.get_agent = AsyncMock(return_value=None)
    response = client.get("/api/agents/999/capabilities", headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_put_agent_capabilities(client):
    _mock_db.get_agent_capabilities = AsyncMock(return_value=[
        AgentCapability(id=1, agent_id=1, capability_name="appointment", is_active=1, config_json='{"slot_duration_minutes": 45}'),
        AgentCapability(id=2, agent_id=1, capability_name="lead", is_active=1, config_json='{}'),
    ])
    response = client.put(
        "/api/agents/1/capabilities",
        json={
            "capabilities": [
                {"capability_name": "appointment", "is_active": 1, "config_json": '{"slot_duration_minutes": 45}'},
                {"capability_name": "lead", "is_active": 1, "config_json": "{}"},
            ]
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert _mock_db.upsert_agent_capability.call_count == 2


def test_put_agent_capabilities_invalid_name(client):
    response = client.put(
        "/api/agents/1/capabilities",
        json={
            "capabilities": [
                {"capability_name": "nonexistent", "is_active": 1, "config_json": "{}"},
            ]
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "nonexistent" in response.json()["detail"]


def test_delete_agent_capability(client):
    _mock_db.get_agent_capabilities = AsyncMock(return_value=[
        AgentCapability(id=1, agent_id=1, capability_name="appointment", is_active=1, config_json='{}'),
    ])
    response = client.delete("/api/agents/1/capabilities/appointment", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    _mock_db.delete_agent_capability.assert_called_once_with(1, "appointment")


def test_delete_agent_capability_404(client):
    _mock_db.get_agent_capabilities = AsyncMock(return_value=[])
    response = client.delete("/api/agents/1/capabilities/appointment", headers=AUTH_HEADERS)
    assert response.status_code == 404

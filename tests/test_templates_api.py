import os
import sqlite3
import sys

import aiosqlite
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.capabilities.appointment import AppointmentCapability
from core.capabilities.base import registry
from core.capabilities.lead import LeadCapability
from core.capabilities.membership import MembershipCapability
from core.capabilities.order import OrderCapability
from db.database import db as global_db

AUTH = {"Authorization": "Bearer test_dashboard_token"}
TEST_DB_PATH = "/tmp/hermes_test/test_templates.db"


@pytest.fixture(autouse=True)
async def setup_test_db():
    os.makedirs("/tmp/hermes_test", exist_ok=True)
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    from core.config import settings
    settings.DB_PATH = TEST_DB_PATH

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

    from db.migrator import run_migrations
    run_migrations(TEST_DB_PATH)

    if global_db._conn:
        await global_db._conn.close()
        global_db._conn = None
    global_db._conn = await aiosqlite.connect(TEST_DB_PATH)
    global_db._conn.row_factory = aiosqlite.Row

    yield

    if global_db._conn:
        await global_db._conn.close()
        global_db._conn = None
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture(autouse=True)
def setup_registry():
    registry._capabilities.clear()
    registry._cache.clear()
    registry.register(OrderCapability)
    registry.register(AppointmentCapability)
    registry.register(MembershipCapability)
    registry.register(LeadCapability)
    yield
    registry._capabilities.clear()
    registry._cache.clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from db.database import get_db
    from main import app

    async def _override():
        return global_db

    app.dependency_overrides[get_db] = _override
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_list_templates(client):
    resp = client.get("/api/templates", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 4
    names = [t["name"] for t in data]
    assert "food_truck" in names
    assert "dentista" in names
    assert "gym" in names
    assert "inmobiliaria" in names


def test_get_template(client):
    resp = client.get("/api/templates/1", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "food_truck"
    assert "{{business_name}}" in data["system_prompt_template"]


def test_get_template_404(client):
    resp = client.get("/api/templates/999", headers=AUTH)
    assert resp.status_code == 404


def test_create_from_template(client):
    resp = client.post(
        "/api/templates/from-template",
        json={"template_id": 1, "fields": {"business_name": "Sanguches Juan", "products": "completos, papas"}},
        headers=AUTH,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] > 0
    assert data["capabilities_created"] == 1

    agent_resp = client.get(f"/api/agents/{data['agent_id']}", headers=AUTH)
    assert agent_resp.status_code == 200
    agent = agent_resp.json()
    assert "Sanguches Juan" in agent["system_prompt"]

    caps_resp = client.get(f"/api/agents/{data['agent_id']}/capabilities", headers=AUTH)
    assert caps_resp.status_code == 200
    caps = caps_resp.json()
    assert len(caps) == 1
    assert caps[0]["capability_name"] == "order"


def test_create_from_template_dentist(client):
    resp = client.post(
        "/api/templates/from-template",
        json={"template_id": 2, "fields": {"business_name": "Clinica Dr. Lopez"}},
        headers=AUTH,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["capabilities_created"] == 1

    caps_resp = client.get(f"/api/agents/{data['agent_id']}/capabilities", headers=AUTH)
    caps = caps_resp.json()
    assert caps[0]["capability_name"] == "appointment"


def test_create_from_template_404(client):
    resp = client.post(
        "/api/templates/from-template",
        json={"template_id": 999, "fields": {}},
        headers=AUTH,
    )
    assert resp.status_code == 404

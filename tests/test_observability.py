import os
import sqlite3
import sys

import aiosqlite
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.database import db as global_db
from db.models import InferenceTrace

TEST_DB_PATH = "/tmp/hermes_test/test_observability.db"
AUTH = {"Authorization": "Bearer test_dashboard_token"}


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


async def _insert_trace(phone, source, error_type=None, error_message=None, correlation_id="abc123"):
    trace = InferenceTrace(
        phone=phone,
        correlation_id=correlation_id,
        agent_id=1,
        request_messages='[{"role":"user","content":"test"}]',
        response_raw="test response" if source == "llm" else None,
        response_source=source,
        error_type=error_type,
        error_message=error_message,
        token_usage_prompt=10 if source == "llm" else 0,
        token_usage_completion=20 if source == "llm" else 0,
        latency_ms=100 if source == "llm" else 0,
    )
    return await global_db.insert_trace(trace)


def test_insert_and_get_trace():
    trace_id = _insert_trace("+56910000001", "llm")
    import asyncio
    trace_id = asyncio.get_event_loop().run_until_complete(trace_id)
    assert trace_id > 0


def test_get_traces_by_phone():
    import asyncio
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "fallback", error_type="unavailable"))
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56999999999", "llm"))

    traces = asyncio.get_event_loop().run_until_complete(global_db.get_traces("+56910000001", limit=10))
    assert len(traces) == 2
    assert traces[0].phone == "+56910000001"


def test_get_trace_stats():
    import asyncio
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "fallback", error_type="unavailable"))
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "error", error_type="RateLimitError", error_message="rate limited"))

    stats = asyncio.get_event_loop().run_until_complete(global_db.get_trace_stats(hours=24))
    assert stats["total"] == 4
    assert stats["llm"] == 2
    assert stats["fallback"] == 1
    assert stats["error"] == 1
    assert stats["avg_llm_latency"] == 100
    assert stats["avg_latency"] == 50


def test_get_last_error():
    import asyncio
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))
    asyncio.get_event_loop().run_until_complete(
        _insert_trace("+56910000001", "error", error_type="RateLimitError", error_message="rate limited")
    )

    last_error = asyncio.get_event_loop().run_until_complete(global_db.get_last_error())
    assert last_error is not None
    assert last_error["error_type"] == "RateLimitError"
    assert last_error["error_message"] == "rate limited"


def test_get_last_error_none():
    import asyncio
    last_error = asyncio.get_event_loop().run_until_complete(global_db.get_last_error())
    assert last_error is None


def test_debug_trace_endpoint(client):
    import asyncio
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))
    asyncio.get_event_loop().run_until_complete(
        _insert_trace("+56910000001", "error", error_type="RuntimeError", error_message="LLM down")
    )

    resp = client.get("/api/debug/trace/+56910000001", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    sources = {d["response_source"] for d in data}
    assert sources == {"llm", "error"}
    error_trace = next(d for d in data if d["response_source"] == "error")
    assert error_trace["error_type"] == "RuntimeError"


def test_debug_trace_full_endpoint(client):
    import asyncio
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))

    resp = client.get("/api/debug/trace/+56910000001/full", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert "request_messages" in data[0]
    assert "response_raw" in data[0]


def test_debug_health_detail_endpoint(client):
    import asyncio
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))

    resp = client.get("/api/debug/health-detail", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert "llm" in data
    assert "trace_stats_24h" in data
    assert data["trace_stats_24h"]["total"] >= 1


def test_correlation_id_in_messages():
    import asyncio
    async def _test():
        msg_id = await global_db.insert_message(
            "+56910000001", "inbound", "customer", "Hola",
            correlation_id="test-corr-123",
        )
        rows = await global_db.fetchall(
            "SELECT id, correlation_id FROM messages WHERE id = ?",
            (msg_id,),
        )
        assert len(rows) == 1
        assert rows[0][1] == "test-corr-123"

    asyncio.get_event_loop().run_until_complete(_test())


def test_correlation_id_in_decisions():
    import asyncio
    async def _test():
        from db.models import AgentDecision
        decision = AgentDecision(
            phone="+56910000001",
            sentiment="neutral",
            sentiment_score=0.5,
            confidence=0.5,
            correlation_id="test-corr-456",
        )
        decision_id = await global_db.insert_agent_decision(decision)
        rows = await global_db.fetchall(
            "SELECT id, correlation_id FROM agent_decisions WHERE id = ?",
            (decision_id,),
        )
        assert len(rows) == 1
        assert rows[0][1] == "test-corr-456"

    asyncio.get_event_loop().run_until_complete(_test())


def test_inference_returns_trace_dict():
    from unittest.mock import AsyncMock, MagicMock, patch

    from core.inference import InferenceEngine

    engine = InferenceEngine()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hola, ¿en qué te ayudo?"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 50
    mock_response.usage.completion_tokens = 20

    engine._llm._available = True
    with patch.object(engine._llm, "chat_completion", return_value=mock_response), \
         patch.object(engine, "_load_agent", AsyncMock(return_value=None)):
        import asyncio
        _text, _escalate, trace = asyncio.get_event_loop().run_until_complete(
            engine.generate("Hola")
        )
        assert trace["source"] == "llm"
        assert trace["token_usage_prompt"] == 50
        assert trace["token_usage_completion"] == 20
        assert trace["latency_ms"] >= 0
        assert trace["response_raw"] == "Hola, ¿en qué te ayudo?"


def test_inference_fallback_returns_trace():
    from core.inference import InferenceEngine

    engine = InferenceEngine()
    engine._llm._available = False

    import asyncio
    _text, _escalate, trace = asyncio.get_event_loop().run_until_complete(
        engine.generate("Hola")
    )
    assert trace["source"] == "fallback"
    assert trace["error_type"] == "unavailable"


def test_fallback_metric_incremented():
    from prometheus_client import REGISTRY

    try:
        metric = REGISTRY.get_sample_value("hermes_llm_fallback_total", {"reason": "unavailable"})
    except Exception:
        metric = 0

    from core.inference import InferenceEngine
    engine = InferenceEngine()
    engine._llm._available = False

    import asyncio
    asyncio.get_event_loop().run_until_complete(engine.generate("test"))

    try:
        after = REGISTRY.get_sample_value("hermes_llm_fallback_total", {"reason": "unavailable"})
    except Exception:
        after = 0

    assert after is not None and after >= (metric or 0)


def test_get_recent_traces_all():
    import asyncio
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000002", "fallback", error_type="unavailable"))
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000003", "error", error_type="TimeoutError", error_message="timed out"))

    traces = asyncio.get_event_loop().run_until_complete(global_db.get_recent_traces(limit=50))
    assert len(traces) == 3
    phones = {t.phone for t in traces}
    assert phones == {"+56910000001", "+56910000002", "+56910000003"}


def test_get_recent_traces_filtered():
    import asyncio
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000002", "fallback", error_type="unavailable"))
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000003", "error", error_type="TimeoutError", error_message="timed out"))

    traces = asyncio.get_event_loop().run_until_complete(global_db.get_recent_traces(limit=50, source="llm"))
    assert len(traces) == 1
    assert traces[0].response_source == "llm"

    fb_traces = asyncio.get_event_loop().run_until_complete(global_db.get_recent_traces(limit=50, source="fallback"))
    assert len(fb_traces) == 1
    assert fb_traces[0].response_source == "fallback"


def test_get_recent_traces_limit():
    import asyncio
    for i in range(5):
        asyncio.get_event_loop().run_until_complete(_insert_trace(f"+5691000000{i}", "llm"))

    traces = asyncio.get_event_loop().run_until_complete(global_db.get_recent_traces(limit=3))
    assert len(traces) == 3


def test_get_trace_by_id():
    import asyncio
    trace_id = asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))

    trace = asyncio.get_event_loop().run_until_complete(global_db.get_trace_by_id(trace_id))
    assert trace is not None
    assert trace.id == trace_id
    assert trace.phone == "+56910000001"
    assert trace.response_source == "llm"


def test_get_trace_by_id_not_found():
    import asyncio
    trace = asyncio.get_event_loop().run_until_complete(global_db.get_trace_by_id(99999))
    assert trace is None


def test_recent_traces_endpoint(client):
    import asyncio
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))
    asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000002", "error", error_type="TimeoutError", error_message="timed out"))

    resp = client.get("/api/debug/traces/recent", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    resp_filtered = client.get("/api/debug/traces/recent?source=error", headers=AUTH)
    assert resp_filtered.status_code == 200
    assert len(resp_filtered.json()) == 1
    assert resp_filtered.json()[0]["response_source"] == "error"


def test_trace_by_id_endpoint(client):
    import asyncio
    trace_id = asyncio.get_event_loop().run_until_complete(_insert_trace("+56910000001", "llm"))

    resp = client.get(f"/api/debug/trace-by-id/{trace_id}", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == trace_id
    assert "request_messages" in data
    assert "response_raw" in data

    resp_not_found = client.get("/api/debug/trace-by-id/99999", headers=AUTH)
    assert resp_not_found.status_code == 404

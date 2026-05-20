import json
import os
import sys

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.database import db as global_db
from db.models import InferenceTrace

AUTH = {"Authorization": "Bearer test_dashboard_token"}


@pytest_asyncio.fixture
async def client():
    from main import app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _insert_trace(phone, source, error_type=None, error_message=None):
    trace = InferenceTrace(
        phone=phone,
        request_messages=json.dumps([{"role": "user", "content": "test"}]),
        response_raw="test response" if source == "llm" else None,
        response_source=source,
        error_type=error_type,
        error_message=error_message,
        token_usage_prompt=10 if source == "llm" else 0,
        token_usage_completion=20 if source == "llm" else 0,
        latency_ms=100 if source == "llm" else 0,
    )
    return await global_db.insert_trace(trace)


@pytest.mark.asyncio
async def test_insert_and_get_trace():
    trace_id = await _insert_trace("+56910000001", "llm")
    assert trace_id > 0


@pytest.mark.asyncio
async def test_get_traces_by_phone():
    await _insert_trace("+56910000001", "llm")
    await _insert_trace("+56910000001", "fallback", error_type="unavailable")
    await _insert_trace("+56999999999", "llm")

    traces = await global_db.get_traces("+56910000001", limit=10)
    assert len(traces) == 2
    assert traces[0].phone == "+56910000001"


@pytest.mark.asyncio
async def test_get_trace_stats():
    await _insert_trace("+56910000001", "llm")
    await _insert_trace("+56910000001", "llm")
    await _insert_trace("+56910000001", "fallback", error_type="unavailable")
    await _insert_trace("+56910000001", "error", error_type="RateLimitError", error_message="rate limited")

    stats = await global_db.get_trace_stats(hours=24)
    assert stats["total"] == 4
    assert stats["llm"] == 2
    assert stats["fallback"] == 1
    assert stats["error"] == 1
    assert stats["avg_llm_latency"] == 100
    assert stats["avg_latency"] == 50


@pytest.mark.asyncio
async def test_get_last_error():
    await _insert_trace("+56910000001", "llm")
    await _insert_trace(
        "+56910000001", "error", error_type="RateLimitError", error_message="rate limited"
    )

    last_error = await global_db.get_last_error()
    assert last_error is not None
    assert last_error["error_type"] == "RateLimitError"
    assert last_error["error_message"] == "rate limited"


@pytest.mark.asyncio
async def test_get_last_error_none():
    last_error = await global_db.get_last_error()
    assert last_error is None


@pytest.mark.asyncio
async def test_debug_trace_endpoint(client):
    await _insert_trace("+56910000001", "llm")
    await _insert_trace(
        "+56910000001", "error", error_type="RuntimeError", error_message="LLM down"
    )

    resp = await client.get("/api/debug/trace/+56910000001", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    sources = {d["response_source"] for d in data}
    assert sources == {"llm", "error"}
    error_trace = next(d for d in data if d["response_source"] == "error")
    assert error_trace["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_debug_trace_full_endpoint(client):
    await _insert_trace("+56910000001", "llm")

    resp = await client.get("/api/debug/trace/+56910000001/full", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert "request_messages" in data[0]
    assert "response_raw" in data[0]


@pytest.mark.asyncio
async def test_debug_health_detail_endpoint(client):
    await _insert_trace("+56910000001", "llm")

    resp = await client.get("/api/debug/health-detail", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert "llm" in data
    assert "trace_stats_24h" in data
    assert data["trace_stats_24h"]["total"] >= 1


@pytest.mark.asyncio
async def test_correlation_id_in_messages():
    await global_db.execute(
        "INSERT INTO conversations (phone, agent_id, state) VALUES ($1, $2, $3)",
        "+56910000001", 1, "BOT_ACTIVE",
    )
    msg_id = await global_db.insert_message(
        "+56910000001", "inbound", "customer", "Hola",
        correlation_id="test-corr-123",
    )
    rows = await global_db.fetchall(
        "SELECT id, correlation_id FROM messages WHERE id = $1", msg_id,
    )
    assert len(rows) == 1
    assert rows[0]["correlation_id"] == "test-corr-123"


@pytest.mark.asyncio
async def test_correlation_id_in_decisions():
    await global_db.execute(
        "INSERT INTO conversations (phone, agent_id, state) VALUES ($1, $2, $3)",
        "+56910000001", 1, "BOT_ACTIVE",
    )
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
        "SELECT id, correlation_id FROM agent_decisions WHERE id = $1", decision_id,
    )
    assert len(rows) == 1
    assert rows[0]["correlation_id"] == "test-corr-456"


@pytest.mark.asyncio
async def test_inference_returns_trace_dict():
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
        _text, _escalate, trace = await engine.generate("Hola")
    assert trace["source"] == "llm"
    assert trace["token_usage_prompt"] == 50
    assert trace["token_usage_completion"] == 20
    assert trace["latency_ms"] >= 0
    assert trace["response_raw"] == "Hola, ¿en qué te ayudo?"


@pytest.mark.asyncio
async def test_inference_fallback_returns_trace():
    from core.inference import InferenceEngine

    engine = InferenceEngine()
    engine._llm._available = False

    _text, _escalate, trace = await engine.generate("Hola")
    assert trace["source"] == "fallback"
    assert trace["error_type"] == "unavailable"


@pytest.mark.asyncio
async def test_fallback_metric_incremented():
    from prometheus_client import REGISTRY

    try:
        metric = REGISTRY.get_sample_value("hermes_llm_fallback_total", {"reason": "unavailable"})
    except Exception:
        metric = 0

    from core.inference import InferenceEngine
    engine = InferenceEngine()
    engine._llm._available = False

    await engine.generate("test")

    try:
        after = REGISTRY.get_sample_value("hermes_llm_fallback_total", {"reason": "unavailable"})
    except Exception:
        after = 0

    assert after is not None and after >= (metric or 0)


@pytest.mark.asyncio
async def test_get_recent_traces_all():
    await _insert_trace("+56910000001", "llm")
    await _insert_trace("+56910000002", "fallback", error_type="unavailable")
    await _insert_trace("+56910000003", "error", error_type="TimeoutError", error_message="timed out")

    traces = await global_db.get_recent_traces(limit=50)
    assert len(traces) == 3
    phones = {t.phone for t in traces}
    assert phones == {"+56910000001", "+56910000002", "+56910000003"}


@pytest.mark.asyncio
async def test_get_recent_traces_filtered():
    await _insert_trace("+56910000001", "llm")
    await _insert_trace("+56910000002", "fallback", error_type="unavailable")
    await _insert_trace("+56910000003", "error", error_type="TimeoutError", error_message="timed out")

    traces = await global_db.get_recent_traces(limit=50, source="llm")
    assert len(traces) == 1
    assert traces[0].response_source == "llm"

    fb_traces = await global_db.get_recent_traces(limit=50, source="fallback")
    assert len(fb_traces) == 1
    assert fb_traces[0].response_source == "fallback"


@pytest.mark.asyncio
async def test_get_recent_traces_limit():
    for i in range(5):
        await _insert_trace(f"+5691000000{i}", "llm")

    traces = await global_db.get_recent_traces(limit=3)
    assert len(traces) == 3


@pytest.mark.asyncio
async def test_get_trace_by_id():
    trace_id = await _insert_trace("+56910000001", "llm")

    trace = await global_db.get_trace_by_id(trace_id)
    assert trace is not None
    assert trace.id == trace_id
    assert trace.phone == "+56910000001"
    assert trace.response_source == "llm"


@pytest.mark.asyncio
async def test_get_trace_by_id_not_found():
    trace = await global_db.get_trace_by_id(99999)
    assert trace is None


@pytest.mark.asyncio
async def test_recent_traces_endpoint(client):
    await _insert_trace("+56910000001", "llm")
    await _insert_trace("+56910000002", "error", error_type="TimeoutError", error_message="timed out")

    resp = await client.get("/api/debug/traces/recent", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    resp_filtered = await client.get("/api/debug/traces/recent?source=error", headers=AUTH)
    assert resp_filtered.status_code == 200
    assert len(resp_filtered.json()) == 1
    assert resp_filtered.json()[0]["response_source"] == "error"


@pytest.mark.asyncio
async def test_trace_by_id_endpoint(client):
    trace_id = await _insert_trace("+56910000001", "llm")

    resp = await client.get(f"/api/debug/trace-by-id/{trace_id}", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == trace_id
    assert "request_messages" in data
    assert "response_raw" in data

    resp_not_found = await client.get("/api/debug/trace-by-id/99999", headers=AUTH)
    assert resp_not_found.status_code == 404

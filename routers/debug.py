import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from core.config import settings
from core.llm_client import llm_client
from db.database import Database, get_db

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/trace/{phone}")
async def get_trace(
    phone: str,
    limit: int = 10,
    db: Database = Depends(get_db),
) -> Any:
    traces = await db.get_traces(phone, limit=limit)
    return [
        {
            "id": t.id,
            "correlation_id": t.correlation_id,
            "agent_id": t.agent_id,
            "response_source": t.response_source,
            "error_type": t.error_type,
            "error_message": t.error_message,
            "token_usage_prompt": t.token_usage_prompt,
            "token_usage_completion": t.token_usage_completion,
            "latency_ms": t.latency_ms,
            "created_at": t.created_at,
        }
        for t in traces
    ]


@router.get("/trace/{phone}/full")
async def get_trace_full(
    phone: str,
    limit: int = 3,
    db: Database = Depends(get_db),
) -> Any:
    traces = await db.get_traces(phone, limit=limit)
    return [
        {
            "id": t.id,
            "correlation_id": t.correlation_id,
            "agent_id": t.agent_id,
            "request_messages": t.request_messages,
            "response_raw": t.response_raw,
            "response_source": t.response_source,
            "error_type": t.error_type,
            "error_message": t.error_message,
            "token_usage_prompt": t.token_usage_prompt,
            "token_usage_completion": t.token_usage_completion,
            "latency_ms": t.latency_ms,
            "created_at": t.created_at,
        }
        for t in traces
    ]


@router.get("/traces/recent")
async def get_recent_traces(
    limit: int = 50,
    source: str | None = None,
    db: Database = Depends(get_db),
) -> Any:
    traces = await db.get_recent_traces(limit=limit, source=source)
    return [
        {
            "id": t.id,
            "phone": t.phone,
            "correlation_id": t.correlation_id,
            "response_source": t.response_source,
            "error_type": t.error_type,
            "token_usage_prompt": t.token_usage_prompt,
            "token_usage_completion": t.token_usage_completion,
            "latency_ms": t.latency_ms,
            "created_at": t.created_at,
        }
        for t in traces
    ]


@router.get("/trace-by-id/{trace_id}")
async def get_trace_by_id(
    trace_id: int,
    db: Database = Depends(get_db),
) -> Any:
    trace = await db.get_trace_by_id(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return {
        "id": trace.id,
        "phone": trace.phone,
        "correlation_id": trace.correlation_id,
        "agent_id": trace.agent_id,
        "request_messages": trace.request_messages,
        "response_raw": trace.response_raw,
        "response_source": trace.response_source,
        "error_type": trace.error_type,
        "error_message": trace.error_message,
        "token_usage_prompt": trace.token_usage_prompt,
        "token_usage_completion": trace.token_usage_completion,
        "latency_ms": trace.latency_ms,
        "created_at": trace.created_at,
    }


@router.get("/health-detail")
async def health_detail(db: Database = Depends(get_db)) -> Any:
    stats = await db.get_trace_stats(hours=24)
    last_error = await db.get_last_error()
    return {
        "llm": {
            "available": llm_client.available,
            "model": settings.LLM_MODEL,
            "base_url": settings.LLM_BASE_URL,
            "key_fingerprint": hashlib.sha256(settings.LLM_API_KEY.encode()).hexdigest()[:8] + "..." if settings.LLM_API_KEY and not settings.LLM_API_KEY.startswith("nvapi-REPLACE") else "not_set",
        },
        "trace_stats_24h": stats,
        "last_error": last_error,
    }

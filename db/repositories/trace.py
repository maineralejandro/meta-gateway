from __future__ import annotations

from typing import Any

from db.models import InferenceTrace, row_to_inference_trace
from db.repositories.base import BaseRepository


class TraceRepository(BaseRepository):
    async def insert(self, trace: InferenceTrace) -> int:
        return await self._insert_returning_id(
            """INSERT INTO inference_traces
            (phone, correlation_id, agent_id, request_messages, response_raw,
            response_source, error_type, error_message, token_usage_prompt,
            token_usage_completion, latency_ms)
            VALUES ($1, $2, $3, $4::jsonb, $5,
            $6, $7, $8, $9, $10, $11) RETURNING id""",
            trace.phone, trace.correlation_id, trace.agent_id,
            trace.request_messages, trace.response_raw,
            trace.response_source, trace.error_type, trace.error_message,
            trace.token_usage_prompt, trace.token_usage_completion, trace.latency_ms,
        )

    async def get_for_phone(self, phone: str, limit: int = 10) -> list[InferenceTrace]:
        rows = await self._fetchall(
            """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
            response_source, error_type, error_message, token_usage_prompt,
            token_usage_completion, latency_ms, created_at
            FROM inference_traces WHERE phone = $1
            ORDER BY created_at DESC LIMIT $2""",
            phone, limit,
        )
        return [t for r in rows if (t := row_to_inference_trace(r)) is not None]

    async def get_stats(self, hours: int = 24) -> dict[str, Any]:
        row = await self._fetchone(
            """SELECT
            COUNT(*) as total,
            SUM(CASE WHEN response_source = 'llm' THEN 1 ELSE 0 END) as llm_count,
            SUM(CASE WHEN response_source = 'fallback' THEN 1 ELSE 0 END) as fallback_count,
            SUM(CASE WHEN response_source = 'error' THEN 1 ELSE 0 END) as error_count,
            ROUND(AVG(CASE WHEN response_source = 'llm' THEN latency_ms END)) as avg_llm_latency,
            ROUND(AVG(latency_ms)) as avg_latency
            FROM inference_traces
            WHERE created_at >= NOW() - ($1 || ' hours')::interval""",
            str(hours),
        )
        if row is None:
            return {"total": 0, "llm": 0, "fallback": 0, "error": 0, "avg_llm_latency": 0, "avg_latency": 0}
        return {
            "total": row["total"] or 0,
            "llm": row["llm_count"] or 0,
            "fallback": row["fallback_count"] or 0,
            "error": row["error_count"] or 0,
            "avg_llm_latency": row["avg_llm_latency"] or 0,
            "avg_latency": row["avg_latency"] or 0,
        }

    async def get_last_error(self) -> dict[str, Any] | None:
        rows = await self._fetchall(
            """SELECT id, phone, correlation_id, error_type, error_message, created_at
            FROM inference_traces
            WHERE response_source = 'error'
            ORDER BY created_at DESC LIMIT 1""",
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r["id"],
            "phone": r["phone"],
            "correlation_id": r["correlation_id"],
            "error_type": r["error_type"],
            "error_message": r["error_message"],
            "created_at": r["created_at"],
        }

    async def get_recent(self, limit: int = 50, source: str | None = None) -> list[InferenceTrace]:
        if source:
            rows = await self._fetchall(
                """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
                response_source, error_type, error_message,
                token_usage_prompt, token_usage_completion, latency_ms, created_at
                FROM inference_traces
                WHERE response_source = $1
                ORDER BY created_at DESC LIMIT $2""",
                source, limit,
            )
        else:
            rows = await self._fetchall(
                """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
                response_source, error_type, error_message,
                token_usage_prompt, token_usage_completion, latency_ms, created_at
                FROM inference_traces
                ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
        return [t for r in rows if (t := row_to_inference_trace(r)) is not None]

    async def get_by_id(self, trace_id: int) -> InferenceTrace | None:
        row = await self._fetchone(
            """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
            response_source, error_type, error_message,
            token_usage_prompt, token_usage_completion, latency_ms, created_at
            FROM inference_traces WHERE id = $1""",
            trace_id,
        )
        return row_to_inference_trace(row)

    async def cleanup(self, days: int = 30) -> int:
        pool = await self._get_pool()
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """WITH deleted AS (DELETE FROM inference_traces
                WHERE created_at < NOW() - ($1 || ' days')::interval
                RETURNING 1)
                SELECT COUNT(*) as cnt FROM deleted""", str(days),
            )
            return row["cnt"] if row else 0

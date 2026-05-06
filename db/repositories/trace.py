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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace.phone,
                trace.correlation_id,
                trace.agent_id,
                trace.request_messages,
                trace.response_raw,
                trace.response_source,
                trace.error_type,
                trace.error_message,
                trace.token_usage_prompt,
                trace.token_usage_completion,
                trace.latency_ms,
            ),
        )

    async def get_for_phone(self, phone: str, limit: int = 10) -> list[InferenceTrace]:
        rows = await self._fetchall(
            """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
            response_source, error_type, error_message, token_usage_prompt,
            token_usage_completion, latency_ms, created_at
            FROM inference_traces WHERE phone = ?
            ORDER BY created_at DESC LIMIT ?""",
            (phone, limit),
        )
        return [t for r in rows if (t := row_to_inference_trace(r)) is not None]

    async def get_stats(self, hours: int = 24) -> dict[str, Any]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN response_source = 'llm' THEN 1 ELSE 0 END) as llm_count,
                SUM(CASE WHEN response_source = 'fallback' THEN 1 ELSE 0 END) as fallback_count,
                SUM(CASE WHEN response_source = 'error' THEN 1 ELSE 0 END) as error_count,
                ROUND(AVG(CASE WHEN response_source = 'llm' THEN latency_ms END)) as avg_llm_latency,
                ROUND(AVG(latency_ms)) as avg_latency
                FROM inference_traces
                WHERE created_at >= datetime('now', ?)""",
            (f"-{hours} hours",),
        )
        row = await cursor.fetchone()
        if row is None:
            return {"total": 0, "llm": 0, "fallback": 0, "error": 0, "avg_llm_latency": 0, "avg_latency": 0}
        return {
            "total": row[0] or 0,
            "llm": row[1] or 0,
            "fallback": row[2] or 0,
            "error": row[3] or 0,
            "avg_llm_latency": row[4] or 0,
            "avg_latency": row[5] or 0,
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
            "id": r[0],
            "phone": r[1],
            "correlation_id": r[2],
            "error_type": r[3],
            "error_message": r[4],
            "created_at": r[5],
        }

    async def get_recent(self, limit: int = 50, source: str | None = None) -> list[InferenceTrace]:
        if source:
            rows = await self._fetchall(
                """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
                          response_source, error_type, error_message,
                          token_usage_prompt, token_usage_completion, latency_ms, created_at
                   FROM inference_traces
                   WHERE response_source = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (source, limit),
            )
        else:
            rows = await self._fetchall(
                """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
                          response_source, error_type, error_message,
                          token_usage_prompt, token_usage_completion, latency_ms, created_at
                   FROM inference_traces
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            )
        return [t for r in rows if (t := row_to_inference_trace(r)) is not None]

    async def get_by_id(self, trace_id: int) -> InferenceTrace | None:
        row = await self._fetchone(
            """SELECT id, phone, correlation_id, agent_id, request_messages, response_raw,
                      response_source, error_type, error_message,
                      token_usage_prompt, token_usage_completion, latency_ms, created_at
               FROM inference_traces WHERE id = ?""",
            (trace_id,),
        )
        return row_to_inference_trace(row)

    async def cleanup(self, days: int = 30) -> int:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "DELETE FROM inference_traces WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        await conn.commit()
        return cursor.rowcount

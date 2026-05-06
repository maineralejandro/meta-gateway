import asyncio
import json
import time
import uuid
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from core.capabilities.base import registry as capability_registry
from core.events import emit
from core.inference import inference_engine
from core.memory import memory_manager
from core.meta_client import meta_client
from core.metrics import (
    ESCALATIONS,
    LLM_ERRORS,
    LLM_LATENCY,
    LLM_REQUESTS,
    MESSAGES_RECEIVED,
    MESSAGES_SENT,
    refresh_active_conversations,
)
from core.security import sanitize_llm_output
from core.sentiment import sentiment_analyzer
from core.task_tracker import track_task
from db.database import get_db
from db.models import AgentDecision, InferenceTrace, Turn

logger = structlog.get_logger()

ESCALATION_KEYWORDS = ["cancelar", "cancela", "molesto", "reclamo", "queja", "devolución"]

SENTIMENT_THRESHOLD = 0.3
CONFIDENCE_THRESHOLD = 0.5

_phone_locks: dict[str, asyncio.Lock] = {}


def _get_phone_lock(phone: str) -> asyncio.Lock:
    return _phone_locks.setdefault(phone, asyncio.Lock())


class HITLRouter:
    def __init__(
        self,
        *,
        db_getter: Any = None,
        inference: Any = None,
        memory: Any = None,
        sentiment: Any = None,
        meta_client_override: Any = None,
    ) -> None:
        self._db_getter = db_getter
        self._inference = inference
        self._memory = memory
        self._sentiment = sentiment
        self._meta_client = meta_client_override

    async def _get_db(self) -> Any:
        if self._db_getter:
            return await self._db_getter()
        return await get_db()

    def _get_inference(self) -> Any:
        if self._inference:
            return self._inference
        return inference_engine

    def _get_memory(self) -> Any:
        if self._memory:
            return self._memory
        return memory_manager

    def _get_sentiment(self) -> Any:
        if self._sentiment:
            return self._sentiment
        return sentiment_analyzer

    def _get_meta_client(self) -> Any:
        if self._meta_client:
            return self._meta_client
        return meta_client

    async def should_escalate(
        self, sentiment_result: dict[str, Any], text: str, llm_escalate: bool
    ) -> tuple[bool, str]:
        sentiment = sentiment_result.get("sentiment", "neutral")
        score = sentiment_result.get("score", 0.5)
        confidence = sentiment_result.get("confidence", 0.5)

        if llm_escalate:
            return True, "llm_requested_escalation"

        if sentiment == "negative" and score < SENTIMENT_THRESHOLD:
            return True, f"negative_sentiment(score={score:.2f})"

        if not llm_escalate and confidence < 0.4:
            return True, f"very_low_confidence({confidence:.2f})"

        t = text.lower()
        for kw in ESCALATION_KEYWORDS:
            if kw in t:
                return True, f"escalation_keyword({kw})"

        return False, ""

    async def _save_decision(
        self, db: Any, message_id: int | None, phone: str, decision_data: dict[str, Any], correlation_id: str = ""
    ) -> AgentDecision:
        decision = AgentDecision(
            message_id=message_id,
            phone=phone,
            sentiment=decision_data["sentiment"],
            sentiment_score=decision_data["sentiment_score"],
            confidence=decision_data["confidence"],
            llm_escalate=1 if decision_data["llm_escalate"] else 0,
            escalate_reason=decision_data.get("escalate_reason"),
            history_count=decision_data["history_count"],
            agent_name=decision_data["agent_name"],
            correlation_id=correlation_id,
        )
        await db.insert_agent_decision(decision)
        return decision

    async def _save_trace(
        self, db: Any, phone: str, correlation_id: str, agent_id: int | None, trace: dict[str, Any]
    ) -> None:
        try:
            trace_record = InferenceTrace(
                phone=phone,
                correlation_id=correlation_id,
                agent_id=agent_id,
                request_messages=trace.get("request_messages", ""),
                response_raw=trace.get("response_raw"),
                response_source=trace.get("source", "error"),
                error_type=trace.get("error_type"),
                error_message=trace.get("error_message"),
                token_usage_prompt=trace.get("token_usage_prompt", 0),
                token_usage_completion=trace.get("token_usage_completion", 0),
                latency_ms=trace.get("latency_ms", 0),
            )
            await db.insert_trace(trace_record)
        except Exception as e:
            logger.error("trace_save_error", phone=phone, error=str(e))

    async def _analyze_sentiment(self, text: str) -> dict[str, Any]:
        try:
            sentiment = self._get_sentiment()
            result = await sentiment.analyze(text)
            logger.debug("sentiment_analyzed", sentiment=result.get("sentiment"), score=result.get("score"))
            return result
        except Exception as e:
            logger.warning("sentiment_analysis_failed", error=str(e))
            return {"sentiment": "neutral", "score": 0.5, "confidence": 0.5}

    async def _resolve_capabilities(self, agent_id: int | None) -> list[Any]:
        try:
            capabilities = await capability_registry.resolve(agent_id)
            logger.debug("capabilities_resolved", count=len(capabilities), names=[c.name for c in capabilities])
            return capabilities
        except Exception as e:
            logger.warning("capability_resolution_failed", error=str(e))
            return []

    async def _build_history(
        self, phone: str, text: str, agent_id: int | None, capabilities: list[Any]
    ) -> list[dict[str, Any]]:
        try:
            memory = self._get_memory()
            history = await memory.build_context(
                phone, current_message=text, agent_id=agent_id, capabilities=capabilities,
            )
            logger.debug("context_built", history_count=len(history))
            return history
        except Exception as e:
            logger.warning("context_build_failed", error=str(e))
            return []

    async def _run_inference(
        self,
        text: str,
        history: list[dict[str, Any]],
        agent_id: int | None,
        capabilities: list[Any],
        phone: str,
        correlation_id: str,
    ) -> tuple[str, bool, dict[str, Any]]:
        inference = self._get_inference()
        LLM_REQUESTS.inc()
        t0 = time.monotonic()
        try:
            response_text, llm_escalate, trace = await inference.generate(
                text, history=history, agent_id=agent_id, capabilities=capabilities,
                phone=phone, correlation_id=correlation_id,
            )
        except Exception:
            LLM_ERRORS.inc()
            raise
        finally:
            LLM_LATENCY.observe(time.monotonic() - t0)
        return response_text, llm_escalate, trace

    def _build_decision_data(
        self,
        sentiment_result: dict[str, Any],
        llm_escalate: bool,
        should_escalate: bool,
        reason: str,
        history_count: int,
    ) -> dict[str, Any]:
        inference = self._get_inference()
        agent_name = ""
        if inference._current_agent:
            agent_name = inference._current_agent.name
        return {
            "sentiment": sentiment_result.get("sentiment", "neutral"),
            "sentiment_score": sentiment_result.get("score", 0.5),
            "confidence": sentiment_result.get("confidence", 0.5),
            "llm_escalate": llm_escalate,
            "escalate_reason": reason if should_escalate else None,
            "history_count": history_count,
            "agent_name": agent_name,
        }

    async def _handle_escalation(
        self,
        phone: str,
        consolidated_text: str,
        correlation_id: str,
        message_ids: list[int],
        session_id: str | None,
        db: Any,
        sentiment_result: dict[str, Any],
        reason: str,
        decision_data: dict[str, Any],
    ) -> None:
        ESCALATIONS.labels(reason=reason.split("(")[0]).inc()
        await db.escalate_conversation(
            phone, sentiment_result["score"], sentiment_result["confidence"], reason
        )

        escalation_msg = "Un momento, te comunico con un atendedor. \U0001f64f"
        client = self._get_meta_client()
        await client.send_text(phone, escalation_msg)
        MESSAGES_SENT.labels(source="bot").inc()
        out_message_id = await db.insert_message(
            phone, "outbound", "bot", escalation_msg,
            session_id=session_id, correlation_id=correlation_id,
        )

        await db.insert_turn(Turn(
            phone=phone,
            user_text=consolidated_text,
            assistant_text=escalation_msg,
            user_correlation_id=correlation_id,
            assistant_correlation_id=correlation_id,
            message_ids=json.dumps(message_ids) if message_ids else "[]",
            session_id=session_id,
        ))

        await self._save_decision(db, out_message_id, phone, decision_data, correlation_id)
        decision_data["message_id"] = out_message_id

        await emit("escalated", {
            "phone": phone,
            "reason": reason,
            "sentiment": sentiment_result,
            "decision": decision_data,
        })

        await refresh_active_conversations(db)
        logger.warning("conversation_escalated", phone=phone, reason=reason)

    async def _handle_reply(
        self,
        phone: str,
        consolidated_text: str,
        response_text: str,
        correlation_id: str,
        message_ids: list[int],
        session_id: str | None,
        db: Any,
        sentiment_result: dict[str, Any],
        capabilities: list[Any],
        decision_data: dict[str, Any],
        trace: dict[str, Any],
    ) -> None:
        await db.update_conversation_sentiment(
            phone, sentiment_result["score"], sentiment_result["confidence"]
        )

        for cap in capabilities:
            response_text = await cap.parse_tags(phone, response_text, cap.config)
        response_text = sanitize_llm_output(response_text)
        client = self._get_meta_client()
        await client.send_text(phone, response_text)
        MESSAGES_SENT.labels(source="bot").inc()
        out_message_id = await db.insert_message(
            phone, "outbound", "bot", response_text,
            session_id=session_id, correlation_id=correlation_id,
        )

        await db.insert_turn(Turn(
            phone=phone,
            user_text=consolidated_text,
            assistant_text=response_text,
            user_correlation_id=correlation_id,
            assistant_correlation_id=correlation_id,
            message_ids=json.dumps(message_ids) if message_ids else "[]",
            session_id=session_id,
        ))

        await self._save_decision(db, out_message_id, phone, decision_data, correlation_id)
        decision_data["message_id"] = out_message_id

        await emit("bot-replied", {
            "phone": phone,
            "response": response_text,
            "direction": "outbound",
            "source": "bot",
            "message_id": out_message_id,
            "decision": decision_data,
        })

        logger.info("bot_replied", phone=phone, response_source=trace.get("source"))
        memory = self._get_memory()
        track_task(asyncio.create_task(_safe_summarize(phone, memory)))


    async def process_inbound_message(self, phone: str, text: str, correlation_id: str | None = None) -> None:
        if not correlation_id:
            correlation_id = uuid.uuid4().hex[:12]
        await self.process_turn(phone, text, correlation_id, [], None)

    async def process_turn(self, phone: str, consolidated_text: str, correlation_id: str, message_ids: list[int], session_id: str | None = None) -> None:
        lock = _get_phone_lock(phone)
        async with lock:
            await self._process_turn_inner(phone, consolidated_text, correlation_id, message_ids, session_id)

    async def _process_turn_inner(self, phone: str, consolidated_text: str, correlation_id: str, message_ids: list[int], session_id: str | None = None) -> None:
        bind_contextvars(correlation_id=correlation_id, phone=phone)
        from core.background import touch_phone_lock
        touch_phone_lock(phone)
        try:
            MESSAGES_RECEIVED.labels(source="customer").inc()
            logger.info("turn_received", phone=phone, text_length=len(consolidated_text), burst_size=len(message_ids))
            db = await self._get_db()
            conv = await db.get_conversation(phone)
            agent_id = conv.agent_id if conv else None
            if session_id is None:
                session_id = conv.current_session_id if conv else None

            sentiment_result = await self._analyze_sentiment(consolidated_text)
            capabilities = await self._resolve_capabilities(agent_id)
            history = await self._build_history(phone, consolidated_text, agent_id, capabilities)
            response_text, llm_escalate, trace = await self._run_inference(
                consolidated_text, history, agent_id, capabilities, phone, correlation_id,
            )

            await self._save_trace(db, phone, correlation_id, agent_id, trace)
            logger.info(
                "inference_completed",
                response_source=trace.get("source"),
                latency_ms=trace.get("latency_ms"),
                is_fallback=trace.get("source") in ("fallback", "error"),
            )

            should_escalate, reason = await self.should_escalate(
                sentiment_result, consolidated_text, llm_escalate
            )

            decision_data = self._build_decision_data(
                sentiment_result, llm_escalate, should_escalate, reason, len(history),
            )

            if should_escalate:
                await self._handle_escalation(
                    phone, consolidated_text, correlation_id, message_ids, session_id,
                    db, sentiment_result, reason, decision_data,
                )
                return

            await self._handle_reply(
                phone, consolidated_text, response_text, correlation_id, message_ids,
                session_id, db, sentiment_result, capabilities, decision_data, trace,
            )

        except Exception as e:
            logger.error("process_turn_error", phone=phone, error=str(e), error_type=type(e).__name__)
            await emit("error", {
                "phone": phone,
                "error": str(e),
            })
        finally:
            clear_contextvars()


hitl_router = HITLRouter()

process_inbound_message = hitl_router.process_inbound_message

async def _safe_summarize(phone: str, memory: Any) -> None:
    try:
        await memory.maybe_summarize(phone)
    except Exception as e:
        logger.error("summarize_error", phone=phone, error=str(e))

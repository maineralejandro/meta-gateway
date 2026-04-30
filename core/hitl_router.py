from db.database import get_db
from core.meta_client import meta_client
from core.inference import inference_engine
from core.sentiment import sentiment_analyzer
from core.order_state import order_state
from db.models import AgentDecision
from routers.ws import manager
import structlog
import asyncio
from core.memory import memory_manager
from core.security import sanitize_llm_output

logger = structlog.get_logger()

ESCALATION_KEYWORDS = ["cancelar", "cancela", "molesto", "reclamo", "queja", "devolución"]

SENTIMENT_THRESHOLD = 0.3
CONFIDENCE_THRESHOLD = 0.5


class HITLRouter:
    async def should_escalate(
        self, sentiment_result: dict, text: str, llm_escalate: bool
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
        self, db, message_id: int | None, phone: str, decision_data: dict
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
        )
        await db.insert_agent_decision(decision)
        return decision

    async def process_inbound_message(self, phone: str, text: str):
        try:
            db = await get_db()
            conv = await db.get_conversation(phone)
            agent_id = conv.agent_id if conv else None

            sentiment_result = await sentiment_analyzer.analyze(text)

            history = await memory_manager.build_context(phone, current_message=text)

            response_text, llm_escalate = await inference_engine.generate(
                text, history=history, agent_id=agent_id
            )

            should_escalate, reason = await self.should_escalate(
                sentiment_result, text, llm_escalate
            )

            agent_name = ""
            if inference_engine._current_agent:
                agent_name = inference_engine._current_agent.name

            decision_data = {
                "sentiment": sentiment_result.get("sentiment", "neutral"),
                "sentiment_score": sentiment_result.get("score", 0.5),
                "confidence": sentiment_result.get("confidence", 0.5),
                "llm_escalate": llm_escalate,
                "escalate_reason": reason if should_escalate else None,
                "history_count": len(history),
                "agent_name": agent_name,
            }

            if should_escalate:
                await db.execute_transaction([
                    ("UPDATE conversations SET sentiment_score=?, confidence=?, state='PENDING_APPROVAL', requires_human_review=1 WHERE phone=?",
                     (sentiment_result["score"], sentiment_result["confidence"], phone)),
                    ("INSERT INTO escalation_events (phone, from_state, to_state, reason, sentiment_score, confidence) VALUES (?, 'BOT_ACTIVE', 'PENDING_APPROVAL', ?, ?, ?)",
                     (phone, reason, sentiment_result["score"], sentiment_result["confidence"])),
                ])

                await meta_client.send_text(
                    phone,
                    "Un momento, te comunico con un atendedor. 🙏",
                )

                conn = await db._get_conn()
                session_id = conv.current_session_id if conv else None
                cursor = await conn.execute(
                    "INSERT INTO messages (phone, direction, source, text, session_id) VALUES (?, 'outbound', 'bot', ?, ?)",
                    (phone, "Un momento, te comunico con un atendedor. 🙏", session_id),
                )
                await conn.commit()
                message_id = cursor.lastrowid

                await self._save_decision(db, message_id, phone, decision_data)
                decision_data["message_id"] = message_id

                await manager.send_to_all({
                    "type": "escalated",
                    "phone": phone,
                    "reason": reason,
                    "sentiment": sentiment_result,
                    "decision": decision_data,
                })

                logger.warning("conversation_escalated", phone=phone, reason=reason)
                return

            await db.execute_transaction([
                ("UPDATE conversations SET sentiment_score=?, confidence=? WHERE phone=?",
                 (sentiment_result["score"], sentiment_result["confidence"], phone)),
            ])

            response_text = order_state.parse_tags(phone, response_text)
            response_text = sanitize_llm_output(response_text)
            await meta_client.send_text(phone, response_text)

            conn = await db._get_conn()
            session_id = conv.current_session_id if conv else None
            cursor = await conn.execute(
                "INSERT INTO messages (phone, direction, source, text, session_id) VALUES (?, 'outbound', 'bot', ?, ?)",
                (phone, response_text, session_id),
            )
            await conn.commit()
            message_id = cursor.lastrowid

            await self._save_decision(db, message_id, phone, decision_data)
            decision_data["message_id"] = message_id

            await manager.send_to_all({
                "type": "bot-replied",
                "phone": phone,
                "response": response_text,
                "direction": "outbound",
                "source": "bot",
                "message_id": message_id,
                "decision": decision_data,
            })

            logger.info("bot_replied", phone=phone)

            # Disparar resumen en background (no bloquea la respuesta)
            asyncio.create_task(memory_manager.maybe_summarize(phone))

        except Exception as e:
            logger.error("process_message_error", phone=phone, error=str(e))
            await manager.send_to_all({
                "type": "error",
                "phone": phone,
                "error": str(e),
            })


hitl_router = HITLRouter()

process_inbound_message = hitl_router.process_inbound_message

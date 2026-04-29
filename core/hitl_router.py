from db.database import get_db
from core.meta_client import meta_client
from core.inference import inference_engine
from core.sentiment import sentiment_analyzer
from routers.ws import manager
import structlog

logger = structlog.get_logger()

ESCALATION_KEYWORDS = ["cancelar", "cancela", "molesto", "reclamo", "queja", "devolución"]

SENTIMENT_THRESHOLD = 0.3
CONFIDENCE_THRESHOLD = 0.7


class HITLRouter:
    async def should_escalate(
        self, sentiment_result: dict, text: str, llm_escalate: bool
    ) -> tuple[bool, str]:
        sentiment = sentiment_result.get("sentiment", "neutral")
        score = sentiment_result.get("score", 0.5)
        confidence = sentiment_result.get("confidence", 0.5)

        if llm_escalate:
            return True, "llm_requested_escalation"

        if sentiment == "negative" or score < SENTIMENT_THRESHOLD:
            return True, f"negative_sentiment(score={score:.2f})"

        if confidence < CONFIDENCE_THRESHOLD:
            return True, f"low_confidence({confidence:.2f})"

        t = text.lower()
        for kw in ESCALATION_KEYWORDS:
            if kw in t:
                return True, f"escalation_keyword({kw})"

        return False, ""

    async def process_inbound_message(self, phone: str, text: str):
        try:
            sentiment_result = await sentiment_analyzer.analyze(text)

            response_text, llm_escalate = await inference_engine.generate(text)

            should_escalate, reason = await self.should_escalate(
                sentiment_result, text, llm_escalate
            )

            db = await get_db()

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
                await db.execute_transaction([
                    ("INSERT INTO messages (phone, direction, source, text) VALUES (?, 'outbound', 'bot', ?)",
                     (phone, "Un momento, te comunico con un atendedor. 🙏")),
                ])

                await manager.send_to_all({
                    "type": "escalated",
                    "phone": phone,
                    "reason": reason,
                    "sentiment": sentiment_result,
                })

                logger.warning("conversation_escalated", phone=phone, reason=reason)
                return

            await db.execute_transaction([
                ("UPDATE conversations SET sentiment_score=?, confidence=? WHERE phone=?",
                 (sentiment_result["score"], sentiment_result["confidence"], phone)),
            ])

            await meta_client.send_text(phone, response_text)
            await db.execute_transaction([
                ("INSERT INTO messages (phone, direction, source, text) VALUES (?, 'outbound', 'bot', ?)",
                 (phone, response_text)),
            ])

            await manager.send_to_all({
                "type": "bot-replied",
                "phone": phone,
                "response": response_text,
                "direction": "outbound",
                "source": "bot",
            })

            logger.info("bot_replied", phone=phone)

        except Exception as e:
            logger.error("process_message_error", phone=phone, error=str(e))
            await manager.send_to_all({
                "type": "error",
                "phone": phone,
                "error": str(e),
            })


hitl_router = HITLRouter()

process_inbound_message = hitl_router.process_inbound_message

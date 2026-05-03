import json
from typing import Any

import structlog

from core.llm_client import LLMClient
from core.order_state import order_state
from db.database import db

logger = structlog.get_logger()

WINDOW_SIZE = 16
SUMMARIZE_THRESHOLD = 15

SUMMARY_PROMPT = """Eres un asistente de gestión de memoria. Actualiza el resumen de esta conversación de WhatsApp.

RESUMEN ANTERIOR:
{previous_summary}

MENSAJES NUEVOS:
{messages}

INSTRUCCIONES:
1. Genera un resumen conciso (máximo 3 frases) que combine el resumen anterior con la información nueva.
2. Extrae datos clave del cliente en formato JSON: nombre, dirección, productos pedidos, monto, preferencias.
3. Si un dato nuevo contradice uno anterior, usa el nuevo.

Responde EXACTAMENTE con este formato JSON:
{{"summary": "resumen aquí", "key_facts": ["dato1", "dato2", ...]}}"""


class MemoryManager:
    def __init__(self) -> None:
        self._llm = LLMClient(max_retries=2, retry_delays=[1.0, 2.0], timeout=30.0)

    async def build_context(self, phone: str, current_message: str | None = None) -> list[dict[str, Any]]:
        memory = await db.get_memory(phone)
        recent_msgs = await db.get_messages(phone, limit=WINDOW_SIZE, desc=True)
        recent_msgs = list(reversed(recent_msgs))

        context = []

        if memory and memory.summary:
            summary_text = f"Resumen de la conversación anterior:\n{memory.summary}"
            if memory.key_facts and memory.key_facts != "[]":
                summary_text += f"\nDatos clave del cliente: {memory.key_facts}"
            context.append({"role": "system", "content": summary_text})

        order_context = await order_state.format_for_context(phone)
        if order_context:
            context.append({"role": "system", "content": order_context})

        for msg in recent_msgs:
            if current_message and msg.direction == "inbound" and msg.text == current_message:
                continue
            if msg.text and not msg.text.startswith("["):
                role = "user" if msg.direction == "inbound" else "assistant"
                context.append({"role": role, "content": msg.text})
            elif msg.text and msg.text.startswith("[location]"):
                context.append({"role": "user", "content": msg.text})

        return context

    async def maybe_summarize(self, phone: str) -> None:
        memory = await db.get_memory(phone)
        total = await db.count_messages(phone)
        already_summarized = memory.total_messages_summarized if memory else 0

        new_since_last = total - already_summarized
        if new_since_last < SUMMARIZE_THRESHOLD:
            return

        client = self._llm.get_client()
        if not client:
            logger.warning("memory_summarize_skipped_no_llm", phone=phone)
            return

        all_msgs = await db.get_messages(phone, limit=total)
        msgs_to_summarize = all_msgs[:-WINDOW_SIZE] if len(all_msgs) > WINDOW_SIZE else all_msgs

        formatted = []
        for msg in msgs_to_summarize:
            prefix = "Cliente" if msg.direction == "inbound" else "Bot"
            formatted.append(f"{prefix}: {msg.text or '[media]'}")
        messages_text = "\n".join(formatted[-30:])

        previous_summary = memory.summary if memory else "Sin resumen previo."

        try:
            response = await self._llm.chat_completion(
                [{
                    "role": "user",
                    "content": SUMMARY_PROMPT.format(
                        previous_summary=previous_summary,
                        messages=messages_text,
                    ),
                }],
                max_tokens=300,
                log_label="memory_retry",
            )

            raw_content = response.choices[0].message.content
            if raw_content is None:
                logger.error("memory_empty_response")
                return
            raw = raw_content.strip()
            try:
                start = raw.find('{')
                end = raw.rfind('}') + 1
                if start != -1 and end != 0:
                    raw = raw[start:end]
                result = json.loads(raw)
            except Exception:
                logger.error("memory_json_parse_error", raw=raw)
                return

            summary = result.get("summary", previous_summary)
            key_facts = json.dumps(result.get("key_facts", []), ensure_ascii=False)

            await db.upsert_memory(phone, summary, key_facts, total)
            logger.info(
                "memory_summarized",
                phone=phone,
                total_messages=total,
                summary_length=len(summary),
            )
        except Exception as e:
            logger.error("memory_summarize_error", phone=phone, error=str(e))


memory_manager = MemoryManager()

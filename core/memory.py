import json
from datetime import UTC, datetime
from typing import Any

import structlog

from core.capabilities.base import BaseCapability
from core.capabilities.base import registry as capability_registry
from core.llm_client import LLMClient

logger = structlog.get_logger()

WINDOW_SIZE = 16
SUMMARIZE_THRESHOLD = 15

EPISODIC_PROMPT = """Eres un asistente de gestión de memoria episódica. Genera un resumen de esta sesión de conversación de WhatsApp.

SESIÓN INICIADA: {session_started}
TURNO ACTUAL: {current_time}

MENSAJES DE LA SESIÓN:
{messages}

INSTRUCCIONES:
1. Genera un resumen detallado de esta sesión específica (máximo 5 frases).
2. Incluye contexto temporal explícito: qué pidió el cliente, cuándo, y el resultado.
3. Menciona datos específicos: productos, montos, dirección, horarios, nombres.
4. Si el cliente expresó preferencias o quejas, inclúyelas.
5. El resumen debe permitir entender qué pasó en esta sesión sin leer los mensajes originales.

Responde con un texto plano (no JSON), comenzando con "Sesión del [fecha] —":"""

SUMMARY_PROMPT = """Eres un asistente de gestión de memoria. Actualiza el resumen de esta conversación de WhatsApp.

RESUMEN ANTERIOR:
{previous_summary}

MENSAJES NUEVOS:
{messages}

INSTRUCCIONES:
1. Genera un resumen conciso (máximo 3 frases) que combine el resumen anterior con la información nueva.
2. Extrae datos clave del cliente en formato JSON: nombre, dirección, productos pedidos, monto, preferencias, horarios habituales, método de pago, alergias o restricciones, quejas previas.
3. Si un dato nuevo contradice uno anterior, usa el nuevo.
4. Sé exhaustivo con los key_facts: cada dato factual del cliente debe ser un item separado.

Responde EXACTAMENTE con este formato JSON:
{{"summary": "resumen aquí", "key_facts": ["dato1", "dato2", ...]}}"""


_MEDIA_TAGS = frozenset(["[image]", "[audio]", "[video]", "[document]", "[sticker]", "[contact]"])


class MemoryManager:
    @staticmethod
    def _format_turn_user_text(user_text: str) -> str | None:
        if not user_text:
            return None
        lines = [line.strip() for line in user_text.split("\n\n") if line.strip()]
        non_media_lines = []
        for line in lines:
            is_media = any(line.lower().startswith(tag) for tag in _MEDIA_TAGS)
            if is_media:
                continue
            non_media_lines.append(line)
        if not non_media_lines:
            return None
        return "\n\n".join(non_media_lines)

    def __init__(self, db: Any = None, llm: LLMClient | None = None) -> None:
        self._db = db
        self._llm = llm or LLMClient(max_retries=2, retry_delays=[1.0, 2.0], timeout=30.0)

    async def _resolve_db(self) -> Any:
        if self._db is not None:
            return self._db
        from db.database import get_db
        return await get_db()

    async def build_context(
        self,
        phone: str,
        current_message: str | None = None,
        agent_id: int | None = None,
        capabilities: list[BaseCapability] | None = None,
    ) -> list[dict[str, Any]]:
        _db = await self._resolve_db()
        memory = await _db.get_memory(phone)
        recent_turns = await _db.get_turns(phone, limit=WINDOW_SIZE, desc=True)
        recent_turns = list(reversed(recent_turns))

        current_session_id = recent_turns[-1].session_id if recent_turns else None

        context = []

        if memory and memory.summary:
            summary_text = f"Resumen de la conversación anterior:\n{memory.summary}"
            if memory.key_facts and memory.key_facts != "[]":
                summary_text += f"\nDatos clave del cliente: {memory.key_facts}"
            context.append({"role": "system", "content": summary_text})

        session_summaries = await _db.get_session_summaries(phone, limit=3)
        session_summaries = [s for s in session_summaries if s["session_id"] != current_session_id]
        if session_summaries:
            reversed_summaries = list(reversed(session_summaries))
            parts = []
            for s in reversed_summaries:
                started = s["started_at"] or "fecha desconocida"
                parts.append(f"Sesión del {started}: {s['summary']}")
            episodic_text = "Resúmenes de sesiones anteriores:\n" + "\n".join(parts)
            context.append({"role": "system", "content": episodic_text})

        resolved = capabilities if capabilities is not None else await capability_registry.resolve(agent_id)
        for cap in resolved:
            cap_context = await cap.format_for_context(phone, cap.config)
            if cap_context:
                context.append({"role": "system", "content": cap_context})

        prev_session_id = None
        for turn in recent_turns:
            user_text = self._format_turn_user_text(turn.user_text)
            if not user_text:
                if not turn.assistant_text:
                    continue
                user_text = "[mensaje multimedia]"
            if turn.session_id != prev_session_id and prev_session_id is not None:
                user_text = f"--- Sesión anterior ---\n{user_text}"
            prev_session_id = turn.session_id
            context.append({"role": "user", "content": user_text})
            context.append({"role": "assistant", "content": turn.assistant_text})

        return context

    async def maybe_summarize(self, phone: str) -> None:
        _db = await self._resolve_db()
        memory = await _db.get_memory(phone)
        total = await _db.count_turns(phone)
        already_summarized = memory.total_messages_summarized if memory else 0

        new_since_last = total - already_summarized
        if new_since_last < SUMMARIZE_THRESHOLD:
            return

        client = self._llm.get_client()
        if not client:
            logger.warning("memory_summarize_skipped_no_llm", phone=phone)
            return

        all_turns = await _db.get_turns(phone, limit=total)

        current_session_id = all_turns[-1].session_id if all_turns else None
        if current_session_id:
            turns_to_summarize = [t for t in all_turns if t.session_id != current_session_id]
        else:
            turns_to_summarize = all_turns[:-WINDOW_SIZE] if len(all_turns) > WINDOW_SIZE else all_turns

        if not turns_to_summarize:
            return

        formatted = []
        for turn in turns_to_summarize:
            formatted.append(f"Cliente: {turn.user_text}")
            formatted.append(f"Bot: {turn.assistant_text}")
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

            await _db.upsert_memory(phone, summary, key_facts, len(turns_to_summarize))
            logger.info(
                "memory_summarized",
                phone=phone,
                total_messages=total,
                summarized_count=len(turns_to_summarize),
                summary_length=len(summary),
            )
        except Exception as e:
            logger.error("memory_summarize_error", phone=phone, error=str(e))

    async def summarize_session(self, phone: str, session_id: str) -> None:
        _db = await self._resolve_db()
        turns = await _db.get_turns_by_session(session_id)
        if not turns:
            logger.info("summarize_session_skip_no_turns", session_id=session_id, phone=phone)
            return

        client = self._llm.get_client()
        if not client:
            logger.warning("summarize_session_skipped_no_llm", phone=phone, session_id=session_id)
            return

        session_row = await _db.fetchone("SELECT started_at FROM sessions WHERE id=?", (session_id,))
        session_started = session_row["started_at"] if session_row else "Fecha desconocida"

        formatted = []
        for turn in turns:
            formatted.append(f"Cliente: {turn.user_text}")
            formatted.append(f"Bot: {turn.assistant_text}")
        messages_text = "\n".join(formatted)

        current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        try:
            response = await self._llm.chat_completion(
                [{
                    "role": "user",
                    "content": EPISODIC_PROMPT.format(
                        session_started=session_started,
                        current_time=current_time,
                        messages=messages_text,
                    ),
                }],
                max_tokens=400,
                log_label="episodic_summarize",
            )

            raw_content = response.choices[0].message.content
            if not raw_content or not raw_content.strip():
                logger.error("summarize_session_empty_response", session_id=session_id)
                return

            summary_text = raw_content.strip()
            await _db.update_session_summary(session_id, summary_text)
            logger.info(
                "session_summarized",
                phone=phone,
                session_id=session_id,
                summary_length=len(summary_text),
                turn_count=len(turns),
            )
        except Exception as e:
            logger.error("summarize_session_error", phone=phone, session_id=session_id, error=str(e))


memory_manager = MemoryManager()

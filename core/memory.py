import json
import asyncio
from db.database import db
from core.config import settings
from core.order_state import order_state
from openai import AsyncOpenAI
import structlog

logger = structlog.get_logger()

WINDOW_SIZE = 16 # Mensajes recientes que van completos al LLM
SUMMARIZE_THRESHOLD = 15  # Cada cuántos mensajes nuevos se genera resumen

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
    def __init__(self):
        self._client = None

    def _get_client(self) -> AsyncOpenAI | None:
        available = bool(
            settings.LLM_API_KEY
            and not settings.LLM_API_KEY.startswith("nvapi-REPLACE")
        )
        if not available:
            return None
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
            )
        return self._client

    async def build_context(self, phone: str, current_message: str | None = None) -> list[dict]:
        """Construye la lista de mensajes para el LLM: resumen + ventana reciente."""
        memory = await db.get_memory(phone)
        recent_msgs = await db.get_messages(phone, limit=WINDOW_SIZE, desc=True)
        recent_msgs = list(reversed(recent_msgs))

        context = []

        # 1. Inyectar resumen como contexto previo
        if memory and memory.summary:
            summary_text = f"Resumen de la conversación anterior:\n{memory.summary}"
            if memory.key_facts and memory.key_facts != "[]":
                summary_text += f"\nDatos clave del cliente: {memory.key_facts}"
            context.append({"role": "system", "content": summary_text})

        # 1b. Inyectar estado del pedido si existe
        order_context = order_state.format_for_context(phone)
        if order_context:
            context.append({"role": "system", "content": order_context})

        # 2. Agregar mensajes recientes (filtrar media sin texto útil)
        # Excluir el mensaje actual (ya se inyecta en inference.py) para evitar duplicación
        for msg in recent_msgs:
            if current_message and msg.direction == "inbound" and msg.text == current_message:
                continue
            if msg.text and not msg.text.startswith("["):
                role = "user" if msg.direction == "inbound" else "assistant"
                context.append({"role": role, "content": msg.text})
            elif msg.text and msg.text.startswith("[location]"):
                context.append({"role": "user", "content": msg.text})

        return context

    async def maybe_summarize(self, phone: str):
        """Comprime mensajes viejos en un resumen si se superó el umbral."""
        memory = await db.get_memory(phone)
        total = await db.count_messages(phone)
        already_summarized = memory.total_messages_summarized if memory else 0

        new_since_last = total - already_summarized
        if new_since_last < SUMMARIZE_THRESHOLD:
            return  # No hay suficientes mensajes nuevos

        client = self._get_client()
        if not client:
            logger.warning("memory_summarize_skipped_no_llm", phone=phone)
            return

        # Obtener los mensajes que aún no se han resumido
        # (todos menos los últimos WINDOW_SIZE que quedan como contexto vivo)
        all_msgs = await db.get_messages(phone, limit=total)
        msgs_to_summarize = all_msgs[:-WINDOW_SIZE] if len(all_msgs) > WINDOW_SIZE else all_msgs

        # Formatear mensajes para el prompt
        formatted = []
        for msg in msgs_to_summarize:
            prefix = "Cliente" if msg.direction == "inbound" else "Bot"
            formatted.append(f"{prefix}: {msg.text or '[media]'}")
        messages_text = "\n".join(formatted[-30:])  # Cap a 30 msgs para no explotar tokens

        previous_summary = memory.summary if memory else "Sin resumen previo."

        try:
            response = await client.chat.completions.create(
                model=settings.LLM_MODEL,
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": SUMMARY_PROMPT.format(
                        previous_summary=previous_summary,
                        messages=messages_text,
                    ),
                }],
            )

            raw = response.choices[0].message.content.strip()
            # Encontrar el JSON en caso de que el modelo devuelva texto adicional
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

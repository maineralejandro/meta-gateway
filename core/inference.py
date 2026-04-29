from openai import AsyncOpenAI
from core.config import settings
import structlog

logger = structlog.get_logger()

SYSTEM_PROMPT = """Eres el asistente virtual de un Food Truck chileno. Tu nombre es Hermes.

Vendes: Completos, Chorrillanas, Papas Fritas, Bebidas.

PRECIOS:
- Completo Normal (carne): $3.700
- Completo Gigante (carne): $4.800
- Completo Italiano: $3.700
- Completo Vienesa: $3.200
- Completo Vienesa Vegano: $4.000
- AS (Anticucho Simple) Normal: $3.700
- AS Gigante: $4.800
- Chorrillana: $8.900
- Salchipapas Individual: $2.800
- Salchipapas Mediana: $5.100
- Papas Fritas Individual: $2.100
- Papas Fritas Mediana: $3.700
- Coca Cola lata: $1.500
- Coca Cola 1.5 Lts: $3.000
- Sprite lata: $1.500
- Fanta lata: $1.500
- Agua mineral: $1.200

PROMOS:
1. Promo Vienesa Normal: Vienesa + Papas Ind. + Bebida = $5.300
2. Promo Vienesa Vegana: Vienesa Vegana + Papas Ind. + Bebida = $6.100
3. Promo AS Normal: AS + Papas Ind. + Bebida = $6.600

REGLAS:
- Siempre responde en español chileno, amable y directo.
- Si el cliente quiere cancelar una orden, responde exactamente: ESCALATE_TO_HUMAN
- Si el cliente está molesto o quejándose, responde exactamente: ESCALATE_TO_HUMAN
- Si no entiendes la pregunta o tienes baja confianza, responde exactamente: ESCALATE_TO_HUMAN
- Para delivery, pide dirección y calcula tarifa.
- Siempre confirma totales antes de cerrar una orden.
"""

ESCALATION_MARKER = "ESCALATE_TO_HUMAN"


class InferenceEngine:
    def __init__(self):
        self.client = None
        self._available = bool(settings.LLM_API_KEY and not settings.LLM_API_KEY.startswith("nvapi-REPLACE"))

    def _get_client(self):
        if self.client is None and self._available:
            self.client = AsyncOpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
            )
        return self.client

    async def generate(self, user_message: str, history: list[dict] | None = None) -> tuple[str, bool]:
        """
        Returns (response_text, should_escalate)
        """
        if not self._available:
            return self._fallback_response(user_message), False

        try:
            client = self._get_client()
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": user_message})

            response = await client.chat.completions.create(
                model=settings.LLM_MODEL,
                max_tokens=500,
                messages=messages,
            )

            text = response.choices[0].message.content.strip()

            if ESCALATION_MARKER in text:
                clean = text.replace(ESCALATION_MARKER, "").strip()
                return clean if clean else "Un momento, te comunico con un atendedor.", True

            return text, False

        except Exception as e:
            logger.error("inference_error", error=str(e))
            return self._fallback_response(user_message), False

    def _fallback_response(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["precio", "cuanto", "cuesta", "vale"]):
            return "🌭 Nuestros precios:\nCompletos desde $3.700\nChorrillana $8.900\n¿Te interesa alguna promo?"
        if any(w in t for w in ["promo", "oferta", "combo"]):
            return "🌟 SUPER PROMOS:\n1. Vienesa+Papas+Bebida $5.300\n2. Vienesa Vegana $6.100\n3. AS+Papas+Bebida $6.600"
        if "delivery" in t:
            return "🛵 Sí hacemos delivery! Danos tu dirección para calcular el costo extra."
        if any(w in t for w in ["hola", "buenas", "hi"]):
            return "🌭 ¡Hola! Bienvenido a Food Truck\n¿Qué deseas ordenar? (Completos, Chorrillanas, Papas, Bebidas)"
        return "🤔 No estoy seguro de tu pregunta. ¿Podrías aclarar?"


inference_engine = InferenceEngine()

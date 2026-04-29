from openai import AsyncOpenAI
from core.config import settings
import structlog

logger = structlog.get_logger()

SENTIMENT_PROMPT = """Analiza el siguiente mensaje de un cliente de WhatsApp y responde SOLO con un JSON:
{"sentiment": "positive"|"neutral"|"negative", "score": 0.0-1.0, "confidence": 0.0-1.0}

- sentiment: positive si el cliente está contento, neutral si es informativo/pregunta, negative si está enojado/frustrado/quejándose
- score: 1.0 = muy positive, 0.5 = neutral, 0.0 = muy negative
- confidence: qué tan seguro estás de tu análisis (0.0-1.0)

Mensaje: {message}"""


class SentimentAnalyzer:
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

    async def analyze(self, text: str) -> dict:
        """
        Returns: {"sentiment": str, "score": float, "confidence": float}
        """
        if not self._available:
            return self._heuristic_analysis(text)

        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=settings.LLM_MODEL,
                max_tokens=100,
                messages=[{"role": "user", "content": SENTIMENT_PROMPT.format(message=text)}],
            )

            raw = response.choices[0].message.content.strip()
            import json
            result = json.loads(raw)
            return {
                "sentiment": result.get("sentiment", "neutral"),
                "score": float(result.get("score", 0.5)),
                "confidence": float(result.get("confidence", 0.5)),
            }

        except Exception as e:
            logger.error("sentiment_analysis_error", error=str(e))
            return self._heuristic_analysis(text)

    def _heuristic_analysis(self, text: str) -> dict:
        negative_words = [
            "molesto", "enojado", "furioso", "terrible", "pésimo", "pesimo", "mal",
            "cancelar", "cancela", "cancelo", "anular", "anula", "anulo",
            "reclamo", "queja", "nunca más", "nunca mas", "devolución", "devolucion",
            "devuelvo", "demora", "demoraron", "lento", "mal servicio", "estafa",
            "mala atención", "mala atencion", "horrible", "desastre", "asqueroso",
            "no funciona", "no llega", "no llega", "frío", "frio", "inservible",
            "pésimo servicio", "no sirve", "no recomiendo", "peor",
        ]
        positive_words = [
            "gracias", "excelente", "excelente", "rico", "genial", "increíble",
            "increible", "delicioso", "perfecto", "buenísimo", "buenisimo",
            "me encantó", "me encanto", "recomiendo", "lo mejor", "fantástico",
            "fantastico", "super", "bueno", "bien", "loved", "amable",
        ]
        t = text.lower()

        is_negative = any(w in t for w in negative_words)

        all_caps_words = [w for w in text.split() if w.isupper() and len(w) > 2]
        has_excessive_caps = len(all_caps_words) >= 3

        has_multiple_exclamation = "!!!" in text or "!!" in t

        is_positive = any(w in t for w in positive_words)

        if is_negative or has_excessive_caps or has_multiple_exclamation:
            score = 0.15 if is_negative else 0.25
            confidence = 0.8 if is_negative else 0.7
            return {"sentiment": "negative", "score": score, "confidence": confidence}

        if is_positive:
            return {"sentiment": "positive", "score": 0.85, "confidence": 0.75}

        return {"sentiment": "neutral", "score": 0.6, "confidence": 0.7}


sentiment_analyzer = SentimentAnalyzer()

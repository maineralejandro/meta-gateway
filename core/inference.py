import time
import json
from openai import AsyncOpenAI
from core.config import settings
from db.database import db
from db.models import Agent
import structlog

logger = structlog.get_logger()


class InferenceEngine:
    def __init__(self, agent_id: int | None = None):
        self.client = None
        self._available = bool(
            settings.LLM_API_KEY and not settings.LLM_API_KEY.startswith("nvapi-REPLACE")
        )
        self.agent_id = agent_id
        self._current_agent: Agent | None = None
        self._prompt_loaded_at = 0
        self._cache_ttl = 60  # seconds

    def _get_client(self):
        if self.client is None and self._available:
            self.client = AsyncOpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
            )
        return self.client

    async def _load_agent(self, force: bool = False) -> Agent | None:
        now = time.time()
        if force or not self._current_agent or (now - self._prompt_loaded_at) > self._cache_ttl:
            logger.info("loading_agent_from_db", agent_id=self.agent_id)
            agent = await db.get_agent(agent_id=self.agent_id, is_active=True)
            if agent:
                self._current_agent = agent
                self._prompt_loaded_at = now
            elif not self._current_agent:
                logger.warning("no_agent_found_in_db")
        return self._current_agent

    async def generate(
        self,
        user_message: str,
        history: list[dict] | None = None,
        agent_id: int | None = None,
    ) -> tuple[str, bool]:
        """
        Returns (response_text, should_escalate)
        """
        # Overwrite agent_id if provided per call
        original_agent_id = self.agent_id
        if agent_id:
            self.agent_id = agent_id
            await self._load_agent(force=True)

        agent = await self._load_agent()

        if not self._available:
            response = await self._fallback_response(user_message, agent)
            # Restore agent_id if it was changed
            self.agent_id = original_agent_id
            return response, False

        try:
            client = self._get_client()
            system_prompt = (
                agent.system_prompt
                if agent
                else "Eres un asistente servicial. Responde de forma clara y directa."
            )
            escalation_marker = agent.escalation_marker if agent else "ESCALATE_TO_HUMAN"

            messages = [{"role": "system", "content": system_prompt}]
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": user_message})

            response = await client.chat.completions.create(
                model=settings.LLM_MODEL,
                max_tokens=500,
                messages=messages,
            )

            text = response.choices[0].message.content.strip()

            # Restore agent_id if it was changed
            self.agent_id = original_agent_id

            if escalation_marker in text:
                clean = text.replace(escalation_marker, "").strip()
                return (
                    clean if clean else "Un momento, te comunico con un atendedor.",
                    True,
                )

            return text, False

        except Exception as e:
            logger.error("inference_error", error=str(e))
            response = await self._fallback_response(user_message, agent)
            # Restore agent_id if it was changed
            self.agent_id = original_agent_id
            return response, False

    async def _fallback_response(self, text: str, agent: Agent | None = None) -> str:
        if not agent:
            return "Lo siento, el sistema no está disponible en este momento."

        try:
            fallbacks = json.loads(agent.fallback_responses)
        except Exception:
            return "Lo siento, el sistema no está disponible en este momento."

        t = text.lower()
        if any(w in t for w in ["precio", "cuanto", "cuesta", "vale"]):
            return fallbacks.get("price", "Consulta de precios no disponible.")
        if any(w in t for w in ["promo", "oferta", "combo"]):
            return fallbacks.get("promo", "No hay promociones vigentes.")
        if "delivery" in t:
            return fallbacks.get("delivery", "Consulta de delivery no disponible.")
        if any(w in t for w in ["hola", "buenas", "hi"]):
            return fallbacks.get("greeting", "¡Hola! ¿En qué puedo ayudarte?")

        return fallbacks.get("default", "🤔 No estoy seguro de tu pregunta. ¿Podrías aclarar?")

    async def reload(self):
        await self._load_agent(force=True)


inference_engine = InferenceEngine()

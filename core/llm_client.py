import asyncio
from typing import Any, cast

import structlog
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from openai.types.chat import ChatCompletion

from core.config import settings

logger = structlog.get_logger()

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAYS = [1.0, 2.0, 4.0]


class LLMClient:
    def __init__(
        self,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delays: list[float] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._client: AsyncOpenAI | None = None
        self._max_retries = max_retries
        self._retry_delays = retry_delays or DEFAULT_RETRY_DELAYS[:max_retries]
        self._timeout = timeout
        self._available = bool(
            settings.LLM_API_KEY
            and not settings.LLM_API_KEY.startswith("nvapi-REPLACE")
        )

    @property
    def available(self) -> bool:
        return self._available

    def get_client(self) -> AsyncOpenAI | None:
        if not self._available:
            return None
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
                timeout=self._timeout,
            )
        return self._client

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 500,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        log_label: str = "llm_retry",
    ) -> ChatCompletion:
        client = self.get_client()
        if client is None:
            raise RuntimeError("LLM client not available")
        kwargs: dict[str, Any] = {
            "model": settings.LLM_MODEL,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return cast(ChatCompletion, await client.chat.completions.create(**kwargs))
            except (RateLimitError, APIConnectionError, APITimeoutError) as e:
                last_err = e
                logger.warning(
                    log_label,
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    error=str(e),
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(self._retry_delays[attempt])
                else:
                    raise last_err from None
        raise RuntimeError("unreachable")


llm_client = LLMClient()

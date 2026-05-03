from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import RateLimitError

from core.llm_client import LLMClient


def test_available_with_valid_key():
    with patch("core.llm_client.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "nvapi-real-key"
        client = LLMClient()
        assert client.available is True


def test_not_available_with_placeholder_key():
    with patch("core.llm_client.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "nvapi-REPLACE-ME"
        client = LLMClient()
        assert client.available is False


def test_not_available_with_empty_key():
    with patch("core.llm_client.settings") as mock_settings:
        mock_settings.LLM_API_KEY = ""
        client = LLMClient()
        assert client.available is False


def test_get_client_returns_none_when_unavailable():
    with patch("core.llm_client.settings") as mock_settings:
        mock_settings.LLM_API_KEY = ""
        mock_settings.LLM_BASE_URL = "https://api.example.com/v1"
        client = LLMClient()
        assert client.get_client() is None


def test_get_client_lazy_init():
    with patch("core.llm_client.settings") as mock_settings, \
         patch("core.llm_client.AsyncOpenAI") as mock_openai:
        mock_settings.LLM_API_KEY = "nvapi-real-key"
        mock_settings.LLM_BASE_URL = "https://api.example.com/v1"
        client = LLMClient(timeout=10.0)
        result = client.get_client()
        assert result is not None
        mock_openai.assert_called_once_with(
            api_key="nvapi-real-key",
            base_url="https://api.example.com/v1",
            timeout=10.0,
        )


def test_get_client_cached():
    with patch("core.llm_client.settings") as mock_settings, \
         patch("core.llm_client.AsyncOpenAI") as mock_openai:
        mock_settings.LLM_API_KEY = "nvapi-real-key"
        mock_settings.LLM_BASE_URL = "https://api.example.com/v1"
        client = LLMClient()
        client.get_client()
        client.get_client()
        assert mock_openai.call_count == 1


@pytest.mark.asyncio
async def test_chat_completion_success():
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="hello"))]

    mock_openai_client = MagicMock()
    mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("core.llm_client.settings") as mock_settings:
        mock_settings.LLM_API_KEY = "nvapi-real-key"
        mock_settings.LLM_BASE_URL = "https://api.example.com/v1"
        mock_settings.LLM_MODEL = "test-model"
        client = LLMClient()
        client._client = mock_openai_client

        result = await client.chat_completion(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
        )
        assert result == mock_response
        mock_openai_client.chat.completions.create.assert_called_once_with(
            model="test-model",
            max_tokens=100,
            messages=[{"role": "user", "content": "hi"}],
        )


@pytest.mark.asyncio
async def test_chat_completion_raises_when_unavailable():
    with patch("core.llm_client.settings") as mock_settings:
        mock_settings.LLM_API_KEY = ""
        client = LLMClient()
        with pytest.raises(RuntimeError, match="not available"):
            await client.chat_completion([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_completion_retry_on_rate_limit():
    mock_response = MagicMock()

    mock_openai_client = MagicMock()
    mock_openai_client.chat.completions.create = AsyncMock(side_effect=[
        RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        ),
        mock_response,
    ])

    with patch("core.llm_client.settings") as mock_settings, \
         patch("core.llm_client.asyncio.sleep", new_callable=AsyncMock):
        mock_settings.LLM_API_KEY = "nvapi-real-key"
        mock_settings.LLM_BASE_URL = "https://api.example.com/v1"
        mock_settings.LLM_MODEL = "test-model"
        client = LLMClient(max_retries=2, retry_delays=[0.1, 0.2])
        client._client = mock_openai_client

        result = await client.chat_completion([{"role": "user", "content": "hi"}])
        assert result == mock_response
        assert mock_openai_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_chat_completion_all_retries_fail():
    from openai import RateLimitError

    mock_openai_client = MagicMock()
    mock_openai_client.chat.completions.create = AsyncMock(side_effect=RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body=None,
    ))

    with patch("core.llm_client.settings") as mock_settings, \
         patch("core.llm_client.asyncio.sleep", new_callable=AsyncMock):
        mock_settings.LLM_API_KEY = "nvapi-real-key"
        mock_settings.LLM_BASE_URL = "https://api.example.com/v1"
        mock_settings.LLM_MODEL = "test-model"
        client = LLMClient(max_retries=2, retry_delays=[0.1, 0.2])
        client._client = mock_openai_client

        with pytest.raises(RateLimitError):
            await client.chat_completion([{"role": "user", "content": "hi"}])
        assert mock_openai_client.chat.completions.create.call_count == 2

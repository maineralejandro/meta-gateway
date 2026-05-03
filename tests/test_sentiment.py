import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm_client import LLMClient
from core.sentiment import SentimentAnalyzer


@pytest.fixture
def analyzer():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a._llm = LLMClient.__new__(LLMClient)
    a._llm._client = None
    a._llm._available = False
    a._llm._max_retries = 2
    a._llm._retry_delays = [1.0, 2.0]
    a._llm._timeout = 30.0
    return a


def test_negative_word_detection(analyzer):
    result = analyzer._heuristic_analysis("Estoy molesto con el servicio")
    assert result["sentiment"] == "negative"
    assert result["score"] < 0.3


def test_negative_cancelar(analyzer):
    result = analyzer._heuristic_analysis("Quiero cancelar mi orden")
    assert result["sentiment"] == "negative"


def test_negative_anular(analyzer):
    result = analyzer._heuristic_analysis("Anula mi pedido por favor")
    assert result["sentiment"] == "negative"


def test_negative_mala_atencion(analyzer):
    result = analyzer._heuristic_analysis("Mala atención, demoraron mucho")
    assert result["sentiment"] == "negative"


def test_caps_detection(analyzer):
    result = analyzer._heuristic_analysis("ESTOY ENOJADO PESIMO HORRIBLE")
    assert result["sentiment"] == "negative"


def test_multiple_exclamation(analyzer):
    result = analyzer._heuristic_analysis("No puedo creerlo!!!")
    assert result["sentiment"] == "negative"


def test_positive_word_detection(analyzer):
    result = analyzer._heuristic_analysis("Gracias, estaba riquísimo")
    assert result["sentiment"] == "positive"
    assert result["score"] > 0.7


def test_positive_excelente(analyzer):
    result = analyzer._heuristic_analysis("Excelente servicio, recomendado")
    assert result["sentiment"] == "positive"


def test_positive_with_double_exclamation(analyzer):
    result = analyzer._heuristic_analysis("Gracias!! Estaba riquísimo")
    assert result["sentiment"] == "positive"
    assert result["score"] > 0.7


def test_positive_with_triple_exclamation(analyzer):
    result = analyzer._heuristic_analysis("Delicioso!!!")
    assert result["sentiment"] == "positive"


def test_negative_with_exclamation_no_positive_words(analyzer):
    result = analyzer._heuristic_analysis("No puedo creerlo!!")
    assert result["sentiment"] == "negative"


def test_mixed_positive_negative_positive_wins(analyzer):
    result = analyzer._heuristic_analysis("Molesto!! Pero gracias")
    assert result["sentiment"] == "positive"


def test_caps_negative_without_positive(analyzer):
    result = analyzer._heuristic_analysis("ESTOY ENOJADO PESIMO HORRIBLE")
    assert result["sentiment"] == "negative"


def test_exclamation_without_positive_stays_negative(analyzer):
    result = analyzer._heuristic_analysis("Horrible!!")
    assert result["sentiment"] == "negative"


def test_neutral(analyzer):
    result = analyzer._heuristic_analysis("Hola, cuánto cuesta el completo?")
    assert result["sentiment"] == "neutral"
    assert 0.4 <= result["score"] <= 0.7


def test_neutral_simple_greeting(analyzer):
    result = analyzer._heuristic_analysis("Buenas tardes")
    assert result["sentiment"] == "neutral"


@pytest.mark.asyncio
async def test_llm_analysis_success():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a._llm = LLMClient.__new__(LLMClient)
    a._llm._client = None
    a._llm._available = True
    a._llm._max_retries = 2
    a._llm._retry_delays = [1.0, 2.0]
    a._llm._timeout = 30.0

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({
            "sentiment": "positive",
            "score": 0.9,
            "confidence": 0.85,
        })))
    ]

    with patch.object(a._llm, "chat_completion", return_value=mock_response), \
         patch.object(a._llm, "get_client", return_value=MagicMock()):
        result = await a.analyze("Me encantó la comida")

    assert result["sentiment"] == "positive"
    assert result["score"] == 0.9
    assert result["confidence"] == 0.85


@pytest.mark.asyncio
async def test_llm_analysis_none_content():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a._llm = LLMClient.__new__(LLMClient)
    a._llm._client = None
    a._llm._available = True
    a._llm._max_retries = 2
    a._llm._retry_delays = [1.0, 2.0]
    a._llm._timeout = 30.0

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=None))]

    with patch.object(a._llm, "chat_completion", return_value=mock_response), \
         patch.object(a._llm, "get_client", return_value=MagicMock()):
        result = await a.analyze("Hola")

    assert result["sentiment"] == "neutral"


@pytest.mark.asyncio
async def test_llm_analysis_invalid_json():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a._llm = LLMClient.__new__(LLMClient)
    a._llm._client = None
    a._llm._available = True
    a._llm._max_retries = 2
    a._llm._retry_delays = [1.0, 2.0]
    a._llm._timeout = 30.0

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="not json at all"))]

    with patch.object(a._llm, "chat_completion", return_value=mock_response), \
         patch.object(a._llm, "get_client", return_value=MagicMock()):
        result = await a.analyze("Hola")

    assert result["sentiment"] == "neutral"


@pytest.mark.asyncio
async def test_llm_analysis_retry_on_rate_limit():
    from openai import RateLimitError

    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a._llm = LLMClient.__new__(LLMClient)
    a._llm._client = None
    a._llm._available = True
    a._llm._max_retries = 2
    a._llm._retry_delays = [1.0, 2.0]
    a._llm._timeout = 30.0

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({
            "sentiment": "neutral", "score": 0.5, "confidence": 0.6,
        })))
    ]

    mock_openai_client = MagicMock()
    mock_openai_client.chat.completions.create = AsyncMock(side_effect=[
        RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        ),
        mock_response,
    ])

    with patch.object(a._llm, "get_client", return_value=mock_openai_client), \
         patch("core.llm_client.asyncio.sleep", new_callable=AsyncMock), \
         patch("core.llm_client.settings") as mock_settings:
        mock_settings.LLM_MODEL = "test-model"
        result = await a.analyze("Hola")

    assert result["sentiment"] == "neutral"
    assert mock_openai_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_llm_analysis_all_retries_fail():
    from openai import RateLimitError

    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a._llm = LLMClient.__new__(LLMClient)
    a._llm._client = None
    a._llm._available = True
    a._llm._max_retries = 2
    a._llm._retry_delays = [1.0, 2.0]
    a._llm._timeout = 30.0

    with patch.object(
        a._llm, "chat_completion",
        side_effect=RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        ),
    ), \
         patch("core.llm_client.asyncio.sleep", new_callable=AsyncMock), \
         patch.object(a._llm, "get_client", return_value=MagicMock()):
        result = await a.analyze("Estoy molesto")

    assert result["sentiment"] == "negative"


@pytest.mark.asyncio
async def test_llm_analysis_client_none():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a._llm = LLMClient.__new__(LLMClient)
    a._llm._client = None
    a._llm._available = True
    a._llm._max_retries = 2
    a._llm._retry_delays = [1.0, 2.0]
    a._llm._timeout = 30.0

    with patch.object(a._llm, "get_client", return_value=None):
        result = await a.analyze("Hola")

    assert result["sentiment"] == "neutral"


@pytest.mark.asyncio
async def test_llm_analysis_generic_exception():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a._llm = LLMClient.__new__(LLMClient)
    a._llm._client = None
    a._llm._available = True
    a._llm._max_retries = 2
    a._llm._retry_delays = [1.0, 2.0]
    a._llm._timeout = 30.0

    with patch.object(a._llm, "chat_completion", side_effect=RuntimeError("unexpected")), \
         patch.object(a._llm, "get_client", return_value=MagicMock()):
        result = await a.analyze("Excelente comida")

    assert result["sentiment"] == "positive"


@pytest.mark.asyncio
async def test_get_client_lazy_init():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a._llm = LLMClient.__new__(LLMClient)
    a._llm._client = None
    a._llm._available = True
    a._llm._max_retries = 2
    a._llm._retry_delays = [1.0, 2.0]
    a._llm._timeout = 30.0

    with patch("core.llm_client.AsyncOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        client = a._llm.get_client()

    assert client is not None
    mock_openai.assert_called_once()


@pytest.mark.asyncio
async def test_get_client_not_available():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a._llm = LLMClient.__new__(LLMClient)
    a._llm._client = None
    a._llm._available = False
    a._llm._max_retries = 2
    a._llm._retry_delays = [1.0, 2.0]
    a._llm._timeout = 30.0

    client = a._llm.get_client()
    assert client is None

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.sentiment import SentimentAnalyzer


@pytest.fixture
def analyzer():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a.client = None
    a._available = False
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
    a.client = None
    a._available = True

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({
            "sentiment": "positive",
            "score": 0.9,
            "confidence": 0.85,
        })))
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch.object(a, "_get_client", return_value=mock_client):
        result = await a.analyze("Me encantó la comida")

    assert result["sentiment"] == "positive"
    assert result["score"] == 0.9
    assert result["confidence"] == 0.85


@pytest.mark.asyncio
async def test_llm_analysis_none_content():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a.client = None
    a._available = True

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=None))]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch.object(a, "_get_client", return_value=mock_client):
        result = await a.analyze("Hola")

    assert result["sentiment"] == "neutral"


@pytest.mark.asyncio
async def test_llm_analysis_invalid_json():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a.client = None
    a._available = True

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="not json at all"))]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch.object(a, "_get_client", return_value=mock_client):
        result = await a.analyze("Hola")

    assert result["sentiment"] == "neutral"


@pytest.mark.asyncio
async def test_llm_analysis_retry_on_rate_limit():
    from openai import RateLimitError

    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a.client = None
    a._available = True

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({
            "sentiment": "neutral", "score": 0.5, "confidence": 0.6,
        })))
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[
        RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        ),
        mock_response,
    ])

    with patch.object(a, "_get_client", return_value=mock_client), \
         patch("core.sentiment.asyncio.sleep", new_callable=AsyncMock):
        result = await a.analyze("Hola")

    assert result["sentiment"] == "neutral"
    assert mock_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_llm_analysis_all_retries_fail():
    from openai import RateLimitError

    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a.client = None
    a._available = True

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body=None,
    ))

    with patch.object(a, "_get_client", return_value=mock_client), \
         patch("core.sentiment.asyncio.sleep", new_callable=AsyncMock):
        result = await a.analyze("Estoy molesto")

    assert result["sentiment"] == "negative"


@pytest.mark.asyncio
async def test_llm_analysis_client_none():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a.client = None
    a._available = True

    with patch.object(a, "_get_client", return_value=None):
        result = await a.analyze("Hola")

    assert result["sentiment"] == "neutral"


@pytest.mark.asyncio
async def test_llm_analysis_generic_exception():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a.client = None
    a._available = True

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("unexpected"))

    with patch.object(a, "_get_client", return_value=mock_client):
        result = await a.analyze("Excelente comida")

    assert result["sentiment"] == "positive"


@pytest.mark.asyncio
async def test_get_client_lazy_init():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a.client = None
    a._available = True

    with patch("core.sentiment.AsyncOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        client = a._get_client()

    assert client is not None
    mock_openai.assert_called_once()


@pytest.mark.asyncio
async def test_get_client_not_available():
    a = SentimentAnalyzer.__new__(SentimentAnalyzer)
    a.client = None
    a._available = False

    client = a._get_client()
    assert client is None

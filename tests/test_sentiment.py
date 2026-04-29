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

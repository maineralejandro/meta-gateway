import hashlib
import hmac
import time
from unittest.mock import MagicMock, patch

import pytest

from core.config import settings
from core.security import RateLimiter, sanitize_llm_output, verify_meta_signature


@pytest.mark.asyncio
async def test_verify_meta_signature_valid():
    # Mock settings
    settings.META_APP_SECRET = "test_secret"
    body = b'{"object":"whatsapp_business_account","entry":[]}'

    # Calcular hash real
    expected_hash = hmac.new(
        b"test_secret",
        body,
        hashlib.sha256
    ).hexdigest()

    # Mock request
    request = MagicMock()
    request.headers = {"X-Hub-Signature-256": f"sha256={expected_hash}"}

    result = await verify_meta_signature(request, body)
    assert result is True

@pytest.mark.asyncio
async def test_verify_meta_signature_invalid():
    settings.META_APP_SECRET = "test_secret"
    body = b'original_body'

    # Mock request con hash de OTRO body
    request = MagicMock()
    request.headers = {"X-Hub-Signature-256": "sha256=invalid_hash"}

    result = await verify_meta_signature(request, body)
    assert result is False

@pytest.mark.asyncio
async def test_verify_meta_signature_missing_header():
    settings.META_APP_SECRET = "test_secret"
    body = b'some_body'

    request = MagicMock()
    request.headers = {} # No header

    result = await verify_meta_signature(request, body)
    assert result is False

@pytest.mark.asyncio
async def test_verify_meta_signature_no_secret_rejects():
    settings.META_APP_SECRET = ""
    settings.SKIP_WEBHOOK_SIGNATURE = False
    body = b'some_body'

    request = MagicMock()
    request.headers = {}

    result = await verify_meta_signature(request, body)
    assert result is False


@pytest.mark.asyncio
async def test_verify_meta_signature_skip_flag():
    settings.META_APP_SECRET = ""
    settings.SKIP_WEBHOOK_SIGNATURE = True
    body = b'some_body'

    request = MagicMock()
    request.headers = {}

    result = await verify_meta_signature(request, body)
    assert result is True


@pytest.mark.asyncio
async def test_signature_mismatch_no_hash_leak():
    settings.META_APP_SECRET = "test_secret"
    body = b'some_body'

    request = MagicMock()
    request.headers = {"X-Hub-Signature-256": "sha256=invalid_hash"}

    with patch("core.security.logger") as mock_logger:
        result = await verify_meta_signature(request, body)

    assert result is False
    mock_logger.warning.assert_called_once_with("webhook_signature_mismatch")
    call_kwargs = mock_logger.warning.call_args[1]
    assert "expected" not in call_kwargs
    assert "provided" not in call_kwargs

def test_rate_limiter():
    limiter = RateLimiter(max_per_minute=5)
    phone = "123456789"

    # Primeras 5 permitidas
    for _ in range(5):
        assert limiter.is_allowed(phone) is True

    # La 6ta rechazada
    assert limiter.is_allowed(phone) is False

    # Diferente teléfono permitida
    assert limiter.is_allowed("987654321") is True

def test_rate_limiter_cleanup():
    limiter = RateLimiter(max_per_minute=10)
    phone = "123"

    # Agregar un timestamp antiguo manualmente
    limiter.requests[phone] = [time.time() - 70] # 70 segundos atrás

    # Al pedir permiso, se limpia el antiguo y se permite
    assert limiter.is_allowed(phone) is True
    assert len(limiter.requests[phone]) == 1 # Solo el nuevo

def test_sanitize_llm_output_truncation():
    long_text = "A" * 3000
    sanitized = sanitize_llm_output(long_text)
    assert len(sanitized) == 2000

def test_sanitize_llm_output_control_chars():
    # \x00 es control, \n es permitido
    text = "Hola\x00Mundo\nLínea 2"
    sanitized = sanitize_llm_output(text)
    assert sanitized == "HolaMundo\nLínea 2"

def test_sanitize_llm_output_strip():
    text = " Hola Mundo \n"
    sanitized = sanitize_llm_output(text)
    assert sanitized == "Hola Mundo"


def test_ip_rate_limiter():
    limiter = RateLimiter(max_per_minute=5)
    ip = "127.0.0.1"

    for _ in range(5):
        assert limiter.is_allowed(ip) is True

    assert limiter.is_allowed(ip) is False
    assert limiter.is_allowed("192.168.1.1") is True


def test_ip_rate_limiter_cleanup():
    limiter = RateLimiter(max_per_minute=10)
    ip = "10.0.0.1"
    limiter.requests[ip] = [time.time() - 70]
    limiter.cleanup()
    assert ip not in limiter.requests

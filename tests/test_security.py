import pytest
import hmac
import hashlib
import time
from unittest.mock import MagicMock, AsyncMock
from core.security import verify_meta_signature, RateLimiter, sanitize_llm_output
from core.config import settings

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
async def test_verify_meta_signature_dev_mode():
    settings.META_APP_SECRET = "" # Vacío = dev mode
    body = b'some_body'
    
    request = MagicMock()
    request.headers = {}
    
    result = await verify_meta_signature(request, body)
    assert result is True # Permisivo en dev

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
    text = "   Hola Mundo   \n"
    sanitized = sanitize_llm_output(text)
    assert sanitized == "Hola Mundo"

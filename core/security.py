import hashlib
import hmac
import time

import structlog
from fastapi import Request

from core.config import settings

logger = structlog.get_logger()

async def verify_meta_signature(request: Request, body: bytes) -> bool:
    """
    Verifica la firma HMAC-SHA256 del webhook de Meta.
    Retorna True solo si la firma es válida, o si SKIP_WEBHOOK_SIGNATURE=True (dev mode).
    Retorna False si la firma es inválida o si no hay secret configurado (sin skip flag).
    """
    secret = settings.META_APP_SECRET
    if not secret:
        if settings.SKIP_WEBHOOK_SIGNATURE:
            logger.warning("webhook_signature_skip_enabled", hint="DO NOT USE IN PRODUCTION")
            return True
        logger.error("webhook_signature_no_secret", hint="Set META_APP_SECRET or SKIP_WEBHOOK_SIGNATURE=true for dev")
        return False

    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        logger.warning("webhook_signature_missing")
        return False

    if not signature_header.startswith("sha256="):
        logger.warning("webhook_signature_invalid_format", header=signature_header)
        return False

    expected_hash = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()

    # signature_header format is "sha256=..."
    provided_hash = signature_header.split("=")[1]

    if hmac.compare_digest(expected_hash, provided_hash):
        return True

    logger.warning("webhook_signature_mismatch")
    return False

class RateLimiter:
    def __init__(self, max_per_minute: int = 30):
        self.max_per_minute = max_per_minute
        self.requests: dict[str, list[float]] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        if key not in self.requests:
            self.requests[key] = []
        self.requests[key] = [t for t in self.requests[key] if now - t < 60]
        if len(self.requests[key]) >= self.max_per_minute:
            return False
        self.requests[key].append(now)
        return True

    def cleanup(self) -> None:
        now = time.time()
        to_delete = []
        for key, timestamps in self.requests.items():
            valid = [t for t in timestamps if now - t < 60]
            if not valid:
                to_delete.append(key)
            else:
                self.requests[key] = valid
        for key in to_delete:
            del self.requests[key]


rate_limiter = RateLimiter(max_per_minute=30)
api_rate_limiter = RateLimiter(max_per_minute=60)

def sanitize_llm_output(text: str) -> str:
    """
    Sanitiza la respuesta del LLM antes de enviarla.
    - Trunca a 2000 caracteres máximo.
    - Elimina caracteres de control excepto newlines.
    - Elimina espacios en blanco redundantes en los extremos.
    """
    if not text:
        return ""

    # Truncar a 2000 caracteres (límite razonable para WhatsApp)
    text = text[:2000]

    # Filtrar caracteres de control (ascii < 32), excepto newline (\n) y carriage return (\r)
    sanitized_chars = []
    for char in text:
        if ord(char) >= 32 or char in ('\n', '\r'):
            sanitized_chars.append(char)

    return "".join(sanitized_chars).strip()

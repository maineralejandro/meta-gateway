import hmac
import hashlib
import time
import structlog
from fastapi import Request
from core.config import settings

logger = structlog.get_logger()

async def verify_meta_signature(request: Request, body: bytes) -> bool:
    """
    Verifica la firma HMAC-SHA256 del webhook de Meta.
    Retorna True si la firma es válida o si META_APP_SECRET no está configurado (modo dev).
    Retorna False si la firma es inválida.
    """
    secret = settings.META_APP_SECRET
    if not secret:
        # Modo dev: si no hay secret, permitimos el request pero loggeamos un warning
        return True

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
    
    logger.warning("webhook_signature_mismatch", expected=expected_hash, provided=provided_hash)
    return False

class RateLimiter:
    """
    Rate limiter básico en memoria por número de teléfono.
    Permite `max_per_minute` requests por minuto por número.
    """
    def __init__(self, max_per_minute: int = 30):
        self.max_per_minute = max_per_minute
        self.requests: dict[str, list[float]] = {}

    def is_allowed(self, phone: str) -> bool:
        now = time.time()
        
        if phone not in self.requests:
            self.requests[phone] = []
            
        # Limpiar requests antiguos (> 60 segundos)
        self.requests[phone] = [req_time for req_time in self.requests[phone] if now - req_time < 60]
        
        if len(self.requests[phone]) >= self.max_per_minute:
            return False
            
        self.requests[phone].append(now)
        return True

    def cleanup(self):
        """Elimina entradas de teléfonos sin actividad reciente."""
        now = time.time()
        phones_to_delete = []
        for phone, timestamps in self.requests.items():
            # Limpiar timestamps antiguos
            valid_timestamps = [req_time for req_time in timestamps if now - req_time < 60]
            if not valid_timestamps:
                phones_to_delete.append(phone)
            else:
                self.requests[phone] = valid_timestamps
                
        for phone in phones_to_delete:
            del self.requests[phone]

# Instancia global del rate limiter
rate_limiter = RateLimiter()

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

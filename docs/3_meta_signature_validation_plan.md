# 🔒 Plan de Implementación: Validación de Firma de Meta + Seguridad

Este plan cubre la validación criptográfica de webhooks de Meta, rate limiting por teléfono, y sanitización de respuestas del LLM.

---

## Fase 1: Configuración y App Secret

**Objetivo:** Agregar el `APP_SECRET` de Meta a la configuración del proyecto.

1.  **Modificar `core/config.py`**:
    *   Agregar campo `META_APP_SECRET: str = ""` a la clase `Settings` (línea ~9, junto a las otras variables de WhatsApp).

2.  **Modificar `.env.example`**:
    *   Agregar la variable documentada:
    ```env
    # === WEBHOOK SECURITY ===
    META_APP_SECRET=REPLACE_ME
    ```

3.  **Modificar `.env`**:
    *   El usuario debe agregar su App Secret real (se obtiene desde Meta Developers → App Settings → Basic → App Secret).

> [!IMPORTANT]
> Sin `META_APP_SECRET` configurado, la validación debe ser **permisiva** (aceptar el request con un warning en logs) para no romper entornos de desarrollo. Solo en producción debe ser estricta.

---

## Fase 2: Middleware de Validación de Firma

**Objetivo:** Verificar que cada POST al webhook provenga realmente de Meta usando HMAC-SHA256.

1.  **Crear `core/security.py`**:
    *   Implementar la función `verify_meta_signature(request: Request) -> bool`:
        1.  Leer el header `X-Hub-Signature-256` del request.
        2.  Si no existe el header y `META_APP_SECRET` está configurado, retornar `False`.
        3.  Leer el body crudo del request (`await request.body()`).
        4.  Calcular `hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()`.
        5.  Comparar con el valor del header (prefijo `sha256=`) usando `hmac.compare_digest()`.
    *   Implementar la clase `RateLimiter`:
        *   `__init__(self, max_per_minute: int = 30)` — almacena timestamps por teléfono en un `dict[str, list[float]]`.
        *   `is_allowed(self, phone: str) -> bool` — limpia timestamps viejos (>60s), retorna `False` si supera el máximo.
        *   `cleanup()` — elimina entradas de teléfonos sin actividad reciente (llamar periódicamente).
    *   Implementar la función `sanitize_llm_output(text: str) -> str`:
        *   Truncar a 2000 caracteres máximo.
        *   Eliminar caracteres de control excepto newlines.
        *   Hacer `.strip()`.

---

## Fase 3: Integración en el Webhook

**Objetivo:** Aplicar la validación de firma y rate limiting en `routers/webhook.py`.

1.  **Modificar `routers/webhook.py`**:
    *   Importar `verify_meta_signature`, `rate_limiter` desde `core.security`.
    *   En `receive_webhook()` (línea 28), **antes** de parsear el JSON:
        1.  Llamar a `verify_meta_signature(request)`.
        2.  Si falla y `META_APP_SECRET` está configurado: retornar `403` y loggear `webhook_signature_invalid`.
        3.  Si `META_APP_SECRET` no está configurado: loggear `webhook_signature_skipped` como warning y continuar.
    *   Después de extraer el `phone` (línea 39):
        1.  Llamar a `rate_limiter.is_allowed(phone)`.
        2.  Si retorna `False`: retornar `{"status": "rate_limited"}` y loggear `rate_limit_exceeded`.
    *   **Problema técnico a resolver**: FastAPI consume el body al leer JSON. Para validar la firma se necesita el body raw primero. Solución:
        ```python
        body = await request.body()
        if not await verify_meta_signature(request, body):
            return Response(status_code=403)
        data = json.loads(body)
        ```

2.  **Modificar `routers/webhook.py` línea 112-114** (bloque except):
    *   **Dejar de exponer errores internos** al caller. Cambiar:
    ```python
    # ANTES:
    return {"status": "error", "detail": str(e)}
    # DESPUÉS:
    return {"status": "error"}
    ```
    *   El detalle del error solo va a logs, nunca al response.

---

## Fase 4: Sanitización de Output del LLM

**Objetivo:** Proteger al usuario final de respuestas malformadas o inyectadas.

1.  **Modificar `core/hitl_router.py`**:
    *   Importar `sanitize_llm_output` desde `core.security`.
    *   Aplicar sanitización al `response_text` **antes** de enviarlo por Meta (línea ~134):
    ```python
    response_text = sanitize_llm_output(response_text)
    await meta_client.send_text(phone, response_text)
    ```

2.  **Modificar `core/inference.py`**:
    *   En `generate()` (línea 86), después de obtener `text` del LLM, aplicar la misma sanitización como defensa en profundidad.

---

## Fase 5: Pruebas

1.  **Crear `tests/test_security.py`**:
    *   **Test de firma válida**: Crear un body, calcular su HMAC con un secret conocido, verificar que `verify_meta_signature` retorne `True`.
    *   **Test de firma inválida**: Pasar un body alterado, verificar que retorne `False`.
    *   **Test de firma ausente**: Sin header `X-Hub-Signature-256`, verificar que retorne `False`.
    *   **Test de rate limiter**: Enviar 31 requests del mismo phone en 1 segundo, verificar que el 31° sea rechazado.
    *   **Test de sanitización**: Pasar textos con caracteres de control, textos de >2000 chars, verificar que se limpien correctamente.

2.  **Test de integración del webhook**:
    *   Mockear un POST al webhook sin firma válida → verificar respuesta 403.
    *   Mockear un POST con firma válida → verificar que procese normalmente.

# Plan: WhatsApp Platform Evolution — De Texto Plano a Experiencia Rica

## Problema

Hermes solo envía texto libre (`type: "text"`) y no recibe mensajes interactivos. Comparado con Jasper's Market (la app demo oficial de Meta), nos faltan:

1. **Interactive Buttons** — el cliente no puede tap, tiene que escribir
2. **Templates** — no podemos iniciar conversaciones fuera de la ventana de 24h
3. **Media Messages** — no podemos enviar imágenes de productos
4. **Status Webhook** — delivered/read solo se loguea, no dispara acciones
5. **Follow-up proactivo** — no hay engagement post-entrega
6. **Health Check roto** — System User tokens fallan en `/debug_token`

Sin templates, el bot está limitado a la ventana de 24h del cliente. Sin interactive buttons, la UX es de chat de texto puro cuando WhatsApp soporta tap-to-act.

---

## Fase 1: Quick Wins (1-2 días)

### 1.1 — Fix `check_token_health()` para System User tokens

**Problema**: `/debug_token` requiere App Access Token (`{app_id}|{app_secret}`) como `access_token`, no el token del usuario. Cuando usamos el System User token como ambos `access_token` e `input_token`, Meta devuelve 400/subcode-33.

**Archivo**: `core/meta_client.py:128-190`

**Cambios**:

#### 1.1.1 — Agregar `META_APP_ID` a config

Archivo: `core/config.py`

```python
META_APP_ID: str = ""
```

El usuario debe agregar `META_APP_ID=<app_id>` al `.env`. Se obtiene de Meta App Dashboard → Settings → App ID.

#### 1.1.2 — Modificar `check_token_health()` con estrategia de 3 niveles

Archivo: `core/meta_client.py`

```python
async def check_token_health(self) -> dict[str, Any]:
    token = self._resolve_token()
    if not token:
        logger.error("meta_token_missing")
        return {"valid": False, "error": "No WHATSAPP_ACCESS_TOKEN found"}

    try:
        app_access_token = None
        if settings.META_APP_ID and settings.META_APP_SECRET:
            app_access_token = f"{settings.META_APP_ID}|{settings.META_APP_SECRET}"

        if app_access_token:
            async with httpx.AsyncClient(
                timeout=15.0,
                headers={"Authorization": f"Bearer {app_access_token}"},
            ) as client:
                resp = await client.get(
                    f"{settings.META_API_URL}/debug_token",
                    params={"input_token": token},
                )
                data = resp.json().get("data", {})
                is_valid = data.get("is_valid", False)
                expires_at = data.get("expires_at")
                token_type = data.get("type", "unknown")
                scopes = data.get("scopes", [])
        else:
            async with httpx.AsyncClient(
                timeout=15.0,
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                resp = await client.get(f"{settings.META_API_URL}/me/permissions")
                if resp.status_code == 200:
                    is_valid = True
                    token_type = "SYSTEM_USER"
                    expires_at = 0
                    scopes = [p["permission"] for p in resp.json().get("data", []) if p.get("status") == "active"]
                else:
                    is_valid = False
                    token_type = "unknown"
                    expires_at = None
                    scopes = []

        from datetime import UTC, datetime
        remaining_min = None
        if expires_at and expires_at > 0:
            remaining_min = (datetime.fromtimestamp(expires_at, tz=UTC) - datetime.now(tz=UTC)).total_seconds() / 60

        self._token_expires_at = expires_at

        if is_valid:
            logger.info(
                "meta_token_valid",
                token_prefix=token[:10],
                token_type=token_type,
                expires_at=expires_at,
                remaining_min=round(remaining_min or 0),
                scopes=",".join(scopes[:5]),
            )
            if remaining_min is not None and remaining_min < 60:
                logger.warning(
                    "meta_token_expiring_soon",
                    remaining_min=round(remaining_min),
                    hint="Generate a System User token for permanent access",
                )
        else:
            error_msg = "unknown"
            error_subcode = None
            if app_access_token:
                err_data = resp.json().get("data", {}).get("error", {})
                error_msg = err_data.get("message", "unknown")
                error_subcode = resp.json().get("error", {}).get("error_subcode")
            logger.error(
                "meta_token_invalid",
                token_prefix=token[:10],
                error=error_msg,
                error_subcode=error_subcode,
                hint="Update WHATSAPP_ACCESS_TOKEN in .env or set env var",
            )

        return {
            "valid": is_valid,
            "type": token_type,
            "expires_at": expires_at,
            "remaining_min": round(remaining_min) if remaining_min else None,
            "scopes": scopes,
        }
    except Exception as e:
        logger.error("meta_token_health_check_failed", error=str(e))
        return {"valid": False, "error": str(e)}
```

**Estrategia de resolución**:

| Condición | Método | Resultado |
|-----------|--------|-----------|
| `META_APP_ID` + `META_APP_SECRET` presentes | `/debug_token` con App Access Token | `is_valid`, `expires_at`, `type`, `scopes` completos |
| Solo `META_APP_SECRET` (sin `META_APP_ID`) | `GET /me/permissions` | `is_valid=True` si 200, `type=SYSTEM_USER`, `expires_at=0` |
| Ninguno | `GET /me/permissions` | Mismo fallback |

#### 1.1.3 — Actualizar `health_check()` para usar resultado de token

Archivo: `core/meta_client.py:113-126`

```python
async def health_check(self) -> dict[str, Any]:
    token_health = await self.check_token_health()
    if token_health.get("valid"):
        return {"connected": True, "status_code": 200, "error": None, **token_health}
    return {"connected": False, "status_code": None, "error": token_health.get("error", "Token invalid"), **token_health}
```

**Test**: `tests/test_meta_client.py`

- Mock `/debug_token` con App Access Token → retorna validación completa
- Mock `/me/permissions` → retorna `is_valid=True`, `type=SYSTEM_USER`
- Mock sin `META_APP_ID` → fallback a `/me/permissions`
- Mock token expirado → `is_valid=False`

**Gate**: `python3 -m pytest tests/test_meta_client.py -v` pasa + `python3 -m mypy core/meta_client.py core/config.py`

---

### 1.2 — Fix `_TOOL_DISCIPLINE_INSTRUCTION` tool name references

**Problema**: Las instrucciones de disciplina de herramientas (líneas 134, 146-148) referencian `order_search_item`, `order_add`, `order_get_menu`, `order_get_categories` — nombres que NO existen. Los tool reales son `cart_add`, `cart_remove`, `cart_clear`, `catalog_list`, `catalog_search`, `catalog_categories`.

Archivo: `core/inference.py:125-149`

**Cambios exactos** (reemplazos de string):

```
Línea 134: "order_add x2"              → "cart_add x2"
Línea 146: "order_search_item"          → "catalog_search"
Línea 147: "order_add"                  → "cart_add"
Línea 148: "order_search_item"          → "catalog_search"
Línea 148: "order_get_menu"             → "catalog_list"
Línea 149: "order_get_categories"       → "catalog_categories"
```

**Nota**: `_TOOL_NAME_PREFIXES` en línea 123 YA tiene `"cart_"` y `"catalog_"` — ese fix ya se hizo. Solo quedan los strings del prompt de instrucciones.

**Gate**: `grep -c "order_add\|order_search\|order_get" core/inference.py` retorna `0`

---

### 1.3 — Interactive Reply Buttons en Meta Client

**Problema**: Solo existe `send_text()`. WhatsApp soporta `type: "interactive"` con `action.buttons[]` que renderiza hasta 3 botones tap-to-reply.

#### 1.3.1 — Agregar `send_interactive_buttons()` a MetaAPIClient

Archivo: `core/meta_client.py`

```python
async def send_interactive_buttons(
    self,
    phone: str,
    body_text: str,
    buttons: list[dict[str, str]],
) -> dict[str, Any]:
    """
    Send interactive button message.

    buttons: list of up to 3 dicts with "id" and "title".
    Example: [{"id": "yes", "title": "Sí"}, {"id": "no", "title": "No"}]
    """
    if len(buttons) > 3:
        logger.warning("interactive_buttons_truncated", count=len(buttons), max=3)
        buttons = buttons[:3]

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": b["id"], "title": b["title"]},
                    }
                    for b in buttons
                ]
            },
        },
    }
    client = await self._get_client()
    resp = await client.post(f"{self.base_url}/messages", json=payload)
    if resp.status_code >= 400:
        error_body = resp.text
        self._log_auth_error(resp.status_code, error_body)
        return {"error": True, "status": resp.status_code, "detail": error_body}
    return resp.json()
```

#### 1.3.2 — Agregar `send_interactive_list()` a MetaAPIClient

WhatsApp soporta `type: "list"` con secciones (hasta 10 opciones total). Útil para `catalog_categories`.

```python
async def send_interactive_list(
    self,
    phone: str,
    body_text: str,
    button_text: str,
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Send interactive list message.

    sections: list of dicts with "title" and "rows" keys.
    Each row: {"id": str, "title": str, "description": str (optional)}.
    Max 10 rows total across all sections.
    """
    total_rows = sum(len(s.get("rows", [])) for s in sections)
    if total_rows > 10:
        logger.warning("interactive_list_truncated", total_rows=total_rows, max=10)

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": button_text,
                "sections": sections,
            },
        },
    }
    client = await self._get_client()
    resp = await client.post(f"{self.base_url}/messages", json=payload)
    if resp.status_code >= 400:
        error_body = resp.text
        self._log_auth_error(resp.status_code, error_body)
        return {"error": True, "status": resp.status_code, "detail": error_body}
    return resp.json()
```

#### 1.3.3 — Recibir mensajes interactivos en webhook

**Problema actual**: `routers/webhook.py:74-87` — cuando `msg_type == "interactive"`, el texto se convierte en `"[interactive]"`, perdiendo el `button_reply.id` o `list_reply.id`.

Archivo: `routers/webhook.py`

Agregar parsing de `interactive` message type dentro del bloque existente:

```python
elif msg_type == "interactive":
    interactive = msg.get("interactive", {})
    interactive_type = interactive.get("type", "")
    if interactive_type == "button_reply":
        reply = interactive.get("button_reply", {})
        text = reply.get("title", reply.get("id", ""))
        media_type = "interactive_button"
        media_url = reply.get("id")
    elif interactive_type == "list_reply":
        reply = interactive.get("list_reply", {})
        text = reply.get("title", reply.get("id", ""))
        media_type = "interactive_list"
        media_url = reply.get("id")
    else:
        text = f"[interactive:{interactive_type}]"
        media_type = "interactive"
```

**Key insight**: `button_reply.id` se guarda en `media_url` y el `title` se guarda como `text`. El LLM recibe `"Sí"` como texto del mensaje (natural). El backend puede consultar `media_url` para saber qué botón se presionó (por ID). La DB guarda ambos para auditoría.

#### 1.3.4 — Integrar buttons en el flujo del HITL Router

**Uso inmediato**: Escalación con botones.

Archivo: `core/hitl_router.py` — `_handle_escalation()`

Hoy envía: `"Un momento, te comunico con un atendedor."`

Agregar botones de "post-escalation":

```python
await meta_client.send_interactive_buttons(
    phone,
    "Un momento, te comunico con un atendedor.",
    [
        {"id": "wait_for_human", "title": "Esperar operador"},
        {"id": "continue_with_bot", "title": "Seguir con el bot"},
    ],
)
```

Cuando el usuario tap "Seguir con el bot", el webhook recibe `interactive_button` con `id=continue_with_bot`. El router puede manejar esto cambiando el estado de vuelta a `BOT_ACTIVE`.

**Test**: `tests/test_webhook.py` — agregar test de payload `interactive` con `button_reply` y `list_reply`.

**Gate**: `python3 -m pytest tests/ -v` + `python3 -m mypy core/meta_client.py routers/webhook.py core/hitl_router.py`

---

### 1.4 — Status Webhook → Persistir + Emitir evento

**Problema**: `routers/webhook.py:153-156` — status updates solo se loguean. No hay persistencia ni evento al dashboard.

#### 1.4.1 — Persistir status en messages table

Nueva migración Alembic: `alembic/versions/xxx_add_message_status_fields.py`

```python
def upgrade() -> None:
    op.add_column("messages", sa.Column("meta_status", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("meta_status_at", sa.TIMESTAMPTZ(), nullable=True))
    op.create_index("idx_messages_meta_status", "messages", ["meta_status"])
```

**Decisión**: Campo en messages table (Opción A) sobre tabla separada. El status más reciente es suficiente — delivered → read se sobreescribe.

#### 1.4.2 — Actualizar webhook handler para persistir + emitir

Archivo: `routers/webhook.py`

```python
if "statuses" in value:
    status_entry = value["statuses"][0]
    status = status_entry.get("status")
    msg_id = status_entry.get("id")
    recipient_phone = status_entry.get("recipient_id")

    logger.info("message_status", status=status, id=msg_id)

    db = await get_db()
    await db.execute(
        "UPDATE messages SET meta_status=$1, meta_status_at=NOW() WHERE meta_message_id=$2",
        status, msg_id,
    )

    await emit("message-status", {
        "phone": recipient_phone,
        "message_id": msg_id,
        "status": status,
    })

    return {"status": "ok"}
```

#### 1.4.3 — Dashboard: mostrar status de mensajes

Agregar handler para `message-status` en `dashboard/hooks/useWSHandlers.ts` para actualizar el estado visual de mensajes (✓ enviado, ✓✓ entregado, ✓✓ leído en azul).

**Test**: `tests/test_webhook.py` — mock de status payload, verificar DB update y event emit.

**Gate**: `python3 -m pytest tests/ -v` + `alembic upgrade head` exitoso

---

## Fase 2: Templates (3-5 días)

### 2.1 — Agregar `META_APP_ID` al `.env` y config

**Ya hecho en Fase 1.1.1** — `META_APP_ID` se agrega a `Settings`. Confirmar que está en `.env`.

---

### 2.2 — Template Management API

**Propósito**: Crear y gestionar templates de WhatsApp programáticamente.

#### 2.2.1 — Modelo de datos

Nueva migración Alembic: `alembic/versions/xxx_whatsapp_templates.py`

```sql
CREATE TABLE whatsapp_templates (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL DEFAULT 1,
    template_name TEXT NOT NULL UNIQUE,
    template_type TEXT NOT NULL DEFAULT 'UTILITY'
        CHECK(template_type IN ('MARKETING', 'UTILITY', 'AUTHENTICATION')),
    category TEXT NOT NULL DEFAULT 'UTILITY',
    language TEXT NOT NULL DEFAULT 'es',
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED', 'PAUSED', 'DISABLED')),
    body_text TEXT NOT NULL,
    header_text TEXT,
    header_image_url TEXT,
    footer_text TEXT,
    buttons_json JSONB DEFAULT '[]',
    meta_template_id TEXT,
    meta_quality_rating TEXT,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_wa_templates_agent ON whatsapp_templates(agent_id);
CREATE INDEX idx_wa_templates_status ON whatsapp_templates(status);
CREATE INDEX idx_wa_templates_name ON whatsapp_templates(template_name);
```

#### 2.2.2 — Repository

Archivo nuevo: `db/repositories/whatsapp_template.py`

```python
class WhatsAppTemplateRepository:
    async def create(self, template: WhatsAppTemplate) -> int
    async def get(self, template_id: int) -> WhatsAppTemplate | None
    async def get_by_name(self, name: str) -> WhatsAppTemplate | None
    async def get_all(self, agent_id: int | None = None, status: str | None = None) -> list[WhatsAppTemplate]
    async def update(self, template_id: int, **fields) -> None
    async def delete(self, template_id: int) -> None
    async def upsert_from_meta(self, meta_data: dict) -> int
```

#### 2.2.3 — Router

Archivo nuevo: `routers/templates.py`

```
POST   /api/templates              — Crear template (local + Meta API)
GET    /api/templates              — Listar templates locales
GET    /api/templates/{id}        — Obtener template por ID
PUT    /api/templates/{id}        — Actualizar template local
DELETE /api/templates/{id}        — Eliminar template (local + Meta API)
POST   /api/templates/sync        — Sincronizar desde Meta API → DB local
POST   /api/templates/{id}/submit — Submit a Meta para aprobación
```

**Flujo de creación**:
1. Dashboard envía `POST /api/templates` con body, header, footer, buttons
2. Backend guarda en DB local (status=PENDING)
3. Backend llama `POST /{business_account_id}/message_templates` en Meta API
4. Meta responde con template ID → se guarda en `meta_template_id`
5. Meta aprueba/rechaza → webhook de status actualiza `status` en DB

#### 2.2.4 — Meta API Client: métodos para templates

Archivo: `core/meta_client.py`

```python
async def create_template(self, waba_id: str, template_data: dict) -> dict[str, Any]:
    """Create a WhatsApp template via Meta API."""
    # POST /{waba_id}/message_templates

async def delete_template(self, waba_id: str, template_name: str) -> dict[str, Any]:
    """Delete a WhatsApp template via Meta API."""
    # DELETE /{waba_id}/message_templates?name={template_name}

async def get_templates(self, waba_id: str) -> list[dict]:
    """List all templates from Meta API."""
    # GET /{waba_id}/message_templates
```

Necesita `WHATSAPP_BUSINESS_ACCOUNT_ID` en config (nuevo campo en `Settings`).

#### 2.2.5 — Template seed para onboarding

Script: `scripts/seed_templates.py`

Templates mínimos para cualquier negocio:

| Template Name | Type | Body |
|---------------|------|------|
| `greeting` | UTILITY | `"Hola {{1}}, gracias por contactarnos."` |
| `order_confirmation` | UTILITY | `"Tu pedido ha sido confirmado. Total: {{1}}."` |
| `delivery_update` | UTILITY | `"Tu pedido está {{1}}. Entrega estimada: {{2}}."` |
| `follow_up` | MARKETING | `"Hola {{1}}, ¿necesitas algo más?"` |
| `appointment_reminder` | UTILITY | `"Recordatorio: tu cita es el {{1}} a las {{2}}."` |

**Gate**: `POST /api/templates` crea template en DB local + Meta API + retorna ID.

---

### 2.3 — Template Sending desde el Agente

**Propósito**: Cuando la ventana de 24h expiró, solo podemos enviar templates aprobados.

#### 2.3.1 — Agregar `send_template()` a MetaAPIClient

Archivo: `core/meta_client.py`

```python
async def send_template(
    self,
    phone: str,
    template_name: str,
    language: str = "es",
    components: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Send a WhatsApp template message.

    components: list of component objects per Meta API spec.
    Example: [
        {"type": "body", "parameters": [{"type": "text", "text": "Juan"}]},
    ]
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
        },
    }
    if components:
        payload["template"]["components"] = components

    client = await self._get_client()
    resp = await client.post(f"{self.base_url}/messages", json=payload)
    if resp.status_code >= 400:
        error_body = resp.text
        self._log_auth_error(resp.status_code, error_body)
        return {"error": True, "status": resp.status_code, "detail": error_body}
    return resp.json()
```

#### 2.3.2 — Lógica de 24h window en HITL Router

Archivo: `core/hitl_router.py` — `_handle_reply()`

Antes de enviar, verificar si estamos dentro de la ventana de 24h:

```python
async def _can_send_free_form(self, phone: str) -> bool:
    """Check if last customer message was within 24h."""
    conv = await db.get_conversation(phone)
    if not conv or not conv.last_message_at:
        return False
    from datetime import UTC, datetime
    elapsed = (datetime.now(tz=UTC) - conv.last_message_at).total_seconds()
    return elapsed < 86400
```

En `_handle_reply()`:

```python
if await self._can_send_free_form(phone):
    await meta_client.send_text(phone, response_text)
else:
    template = await self._select_template_for_reply(response_text)
    if template:
        await meta_client.send_template(phone, template["name"], components=template["components"])
    else:
        logger.warning("no_template_for_offline_reply", phone=phone)
```

#### 2.3.3 — Template selection: heurística simple

```python
async def _select_template_for_reply(self, reply_text: str) -> dict | None:
    text_lower = reply_text.lower()
    templates = {
        "order_confirmation": ["pedido", "confirmado", "orden", "total"],
        "appointment_reminder": ["cita", "recordatorio", "hora"],
        "follow_up": ["necesitas", "ayuda"],
    }
    for template_name, keywords in templates.items():
        if any(kw in text_lower for kw in keywords):
            return {"name": template_name, "components": []}
    return {"name": "greeting", "components": []}
```

**Gate**: Cuando `last_message_at` > 24h, `send_template()` se usa en vez de `send_text()`. Test con mock de datetime.

---

### 2.4 — Limited Time Offer Template

**Propósito**: WhatsApp renderiza nativamente un timer + botón copiar código para templates de tipo `limited_time_offer`.

#### 2.4.1 — Agregar campos LTO a promotions

Nueva migración: `alembic/versions/xxx_add_lto_template_fields.py`

```python
def upgrade() -> None:
    op.add_column("promotions", sa.Column("template_name", sa.Text(), nullable=True))
    op.add_column("promotions", sa.Column("coupon_code", sa.Text(), nullable=True))
    op.add_column("promotions", sa.Column("offer_expiration_ts", sa.TIMESTAMPTZ(), nullable=True))
```

#### 2.4.2 — Crear template LTO via Meta API

Payload para un LTO template:

```json
{
  "name": "lto_berry_sale",
  "category": "MARKETING",
  "language": "es",
  "components": [
    {
      "type": "BODY",
      "text": "Oferta por tiempo limitado: {{1}} con {{2}}% de descuento. Usa el código {{3}}."
    },
    {
      "type": "BUTTON",
      "sub_type": "COPY_CODE",
      "text": "Copiar código"
    },
    {
      "type": "LIMITED_TIME_OFFER",
      "offer_expiration": "2026-05-27T00:00:00Z"
    }
  ]
}
```

WhatsApp renderiza: mensaje + countdown timer + botón "Copiar código" nativo.

**Gate**: Template LTO creado en Meta → aprobado → `send_template()` lo envía → WhatsApp muestra timer + botón copiar.

---

## Fase 3: Rich Media (2-3 días)

### 3.1 — Media Messages (imágenes)

#### 3.1.1 — Agregar `send_image()` a MetaAPIClient

Archivo: `core/meta_client.py`

```python
async def send_image(
    self,
    phone: str,
    image_url: str,
    caption: str = "",
) -> dict[str, Any]:
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "image",
        "image": {"link": image_url},
    }
    if caption:
        payload["image"]["caption"] = caption

    client = await self._get_client()
    resp = await client.post(f"{self.base_url}/messages", json=payload)
    if resp.status_code >= 400:
        error_body = resp.text
        self._log_auth_error(resp.status_code, error_body)
        return {"error": True, "status": resp.status_code, "detail": error_body}
    return resp.json()
```

**Nota**: WhatsApp acepta `"link"` (URL pública) o `"id"` (media ID subido previamente). Empezamos con `"link"` que es más simple — el negocio hostea las imágenes.

#### 3.1.2 — Agregar campo `image_url` al catálogo

Nueva migración: `alembic/versions/xxx_add_catalog_image_url.py`

```python
def upgrade() -> None:
    op.add_column("catalog_items", sa.Column("image_url", sa.Text(), nullable=True))
```

#### 3.1.3 — Inyectar URLs en el contexto del LLM

Archivo: `core/capabilities/cart.py` — `format_for_context()`

Cuando se lista un producto que tiene `image_url`, incluirlo en el contexto:

```
- frutilla ($3990/kg) [IMG: https://example.com/frutilla.jpg]
```

El LLM puede entonces decidir usar el tool `send_product_image`.

#### 3.1.4 — Tool `send_product_image` para el LLM

Agregar como capability del cart:

```python
{
    "type": "function",
    "function": {
        "name": "send_product_image",
        "description": "Enviar imagen de un producto al cliente.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_key": {"type": "string", "description": "Key del producto"},
            },
            "required": ["item_key"],
        },
    },
}
```

Implementación: busca `item_key` en catálogo → obtiene `image_url` → llama `meta_client.send_image()`.

Si el producto no tiene imagen: retorna error `"Este producto no tiene imagen disponible"`.

**Gate**: `send_image()` funciona con URL pública. Catálogo tiene `image_url`. LLM puede usar `send_product_image` tool.

---

### 3.2 — Interactive List Messages para Catálogo

**Ya implementado en 1.3.2** — `send_interactive_list()`. Ahora lo integramos con el catálogo.

#### 3.2.1 — Tool `show_category_menu` para el LLM

```python
{
    "type": "function",
    "function": {
        "name": "show_category_menu",
        "description": "Mostrar menú interactivo de categorías o productos como lista nativa de WhatsApp.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Categoría a mostrar. Vacío = todas las categorías."
                },
            },
        },
    },
}
```

Implementación:
- Si `category` está vacío → lista de categorías con item_count
- Si `category` tiene valor → lista de productos de esa categoría

#### 3.2.2 — Flujo: tap → agregar al carrito

Cuando el usuario selecciona un producto de la lista, el webhook recibe `list_reply.id = item_key`. El router puede:
1. Si el `id` es un item_key válido → enviar buttons: "Agregar al carrito" / "Ver detalles"
2. Si el usuario tap "Agregar" → ejecutar `cart_add` automáticamente

Flujo visual: **lista → selección → confirmación → carrito** en vez de texto libre.

**Gate**: `show_category_menu` envía lista nativa → usuario selecciona → bot agrega al carrito.

---

## Fase 4: Proactive Engagement (2-3 días)

### 4.1 — Follow-up Post-Delivery

**Propósito**: Cuando un mensaje del bot cambia a `delivered`, programar un follow-up automático.

#### 4.1.1 — Tabla de scheduled messages

Nueva migración: `alembic/versions/xxx_add_scheduled_messages.py`

```sql
CREATE TABLE scheduled_messages (
    id SERIAL PRIMARY KEY,
    phone TEXT NOT NULL,
    template_name TEXT NOT NULL,
    components_json JSONB DEFAULT '[]',
    scheduled_at TIMESTAMPTZ NOT NULL,
    triggered_by_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(status IN ('PENDING', 'SENT', 'CANCELLED', 'FAILED')),
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

CREATE INDEX idx_scheduled_messages_due ON scheduled_messages(scheduled_at)
    WHERE status = 'PENDING';
```

#### 4.1.2 — Programar follow-up al recibir status "delivered"

Archivo: `routers/webhook.py` — en el handler de status (Fase 1.4.2):

```python
if status == "delivered":
    await db.execute(
        """INSERT INTO scheduled_messages
        (phone, template_name, components_json, scheduled_at, triggered_by_message_id, status)
        VALUES ($1, 'follow_up', '[]', NOW() + INTERVAL '30 minutes', $2, 'PENDING')""",
        recipient_phone, msg_id,
    )
```

#### 4.1.3 — Background worker para enviar scheduled messages

Archivo nuevo: `core/scheduler.py`

```python
class MessageScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._process_due_messages()
            except Exception as e:
                logger.error("scheduler_error", error=str(e))
            await asyncio.sleep(60)

    async def _process_due_messages(self) -> None:
        db = await get_db()
        rows = await db.fetchall(
            """SELECT id, phone, template_name, components_json
            FROM scheduled_messages
            WHERE status = 'PENDING' AND scheduled_at <= NOW()
            ORDER BY scheduled_at LIMIT 50"""
        )
        for row in rows:
            try:
                components = json.loads(row["components_json"]) if row["components_json"] else []
                result = await meta_client.send_template(
                    row["phone"], row["template_name"], components=components
                )
                status = "SENT" if not result.get("error") else "FAILED"
                await db.execute(
                    "UPDATE scheduled_messages SET status=$1, sent_at=NOW() WHERE id=$2",
                    status, row["id"],
                )
            except Exception as e:
                logger.error("scheduled_message_failed", id=row["id"], error=str(e))
```

#### 4.1.4 — Integrar scheduler en lifespan

Archivo: `main.py` — agregar al lifespan event:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await message_scheduler.start()
    yield
    await message_scheduler.stop()
    await close_db()
```

**Gate**: Scheduled message se crea al recibir "delivered" → scheduler lo envía a los 30 min → template se envía.

---

### 4.2 — Scheduled Messages (Reminders + Re-engagement)

#### 4.2.1 — API para crear scheduled messages

Archivo: `routers/templates.py` (extender)

```
POST   /api/scheduled-messages          — Programar mensaje
GET    /api/scheduled-messages          — Listar programados
DELETE /api/scheduled-messages/{id}     — Cancelar programado
```

#### 4.2.2 — Casos de uso

| Caso | Template | Trigger |
|------|----------|---------|
| Recordatorio de cita | `appointment_reminder` | 24h antes de la cita |
| Follow-up post-compra | `follow_up` | 30 min post-delivery (Fase 4.1) |
| Re-engagement | `follow_up` | 7 días sin actividad |

#### 4.2.3 — Programar reminder al crear cita

En `AppointmentCapability`, cuando se guarda una cita:

```python
await db.execute(
    """INSERT INTO scheduled_messages (phone, template_name, components_json, scheduled_at, status)
    VALUES ($1, 'appointment_reminder', $2, $3, 'PENDING')""",
    phone,
    json.dumps([{"type": "body", "parameters": [
        {"type": "text", "text": appointment_date},
        {"type": "text", "text": appointment_time},
    ]}]),
    appointment_datetime - timedelta(hours=24),
)
```

#### 4.2.4 — Re-engagement automático

Background job (daily): buscar conversaciones con `last_message_at` > 7 días y sin scheduled message pendiente → crear scheduled message con template `follow_up`.

**Gate**: Cita creada → reminder programado → scheduler envía a la hora correcta.

---

## Fase 5 (Opcional): Media Card Carousel

WhatsApp soporta templates con carousel de hasta 10 cards (imagen + body + botones). Payload complejo, requiere template de tipo carousel que Meta aprobó recientemente (2024).

**Decisión**: Postponer hasta que las Fases 1-4 estén estables y validadas con usuarios reales.

---

## Resumen de Archivos Nuevos y Modificados

### Archivos Nuevos

| Archivo | Fase | Propósito |
|---------|------|-----------|
| `db/repositories/whatsapp_template.py` | 2.2 | Repository de templates |
| `routers/templates.py` | 2.2 | Router CRUD de templates |
| `core/scheduler.py` | 4.1 | Background worker para scheduled messages |
| `scripts/seed_templates.py` | 2.2 | Seed de templates iniciales |
| `alembic/versions/xxx_add_message_status_fields.py` | 1.4 | meta_status en messages |
| `alembic/versions/xxx_whatsapp_templates.py` | 2.2 | Tabla whatsapp_templates |
| `alembic/versions/xxx_add_lto_template_fields.py` | 2.4 | Campos LTO en promotions |
| `alembic/versions/xxx_add_catalog_image_url.py` | 3.1 | image_url en catalog_items |
| `alembic/versions/xxx_add_scheduled_messages.py` | 4.1 | Tabla scheduled_messages |

### Archivos Modificados

| Archivo | Fase | Cambio |
|---------|------|--------|
| `core/config.py` | 1.1, 2.2 | Agregar `META_APP_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID` |
| `core/meta_client.py` | 1.1, 1.3, 2.2, 2.3, 3.1 | `check_token_health()` fix, `send_interactive_buttons()`, `send_interactive_list()`, `send_template()`, `send_image()`, `create_template()`, `get_templates()`, `delete_template()` |
| `routers/webhook.py` | 1.3, 1.4 | Parsing de interactive messages, persistir status |
| `core/inference.py` | 1.2 | Fix tool name references en _TOOL_DISCIPLINE_INSTRUCTION |
| `core/hitl_router.py` | 1.3, 2.3 | Buttons en escalación, 24h window logic |
| `core/capabilities/cart.py` | 3.1, 3.2 | `send_product_image` tool, `show_category_menu` tool, image_url en contexto |
| `db/database.py` | 1.4, 2.2 | Agregar `whatsapp_templates` repo, `scheduled_messages` repo |
| `dashboard/hooks/useWSHandlers.ts` | 1.4 | Handler para `message-status` event |
| `main.py` | 4.1 | Integrar `MessageScheduler` en lifespan |

### Config Nuevas en `.env`

| Variable | Fase | Propósito |
|----------|------|-----------|
| `META_APP_ID` | 1.1 | App ID para App Access Token |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | 2.2 | WABA ID para template management API |
| `FOLLOW_UP_DELAY_MINUTES` | 4.1 | Minutos post-delivery para follow-up (default: 30) |
| `RE_ENGAGEMENT_DAYS` | 4.2 | Días sin actividad para re-engagement (default: 7) |

---

## Quality Gates por Fase

### Fase 1

- [ ] `python3 -m pytest tests/ -v` — todos pasan
- [ ] `python3 -m mypy core/ routers/` — 0 errores
- [ ] `python3 -m ruff check .` — 0 errores
- [ ] `grep -r "order_add\|order_search\|order_get" core/inference.py` — 0 matches
- [ ] Webhook recibe `interactive` → texto correcto + `media_url` = button ID
- [ ] `check_token_health()` retorna `valid: true` para System User token
- [ ] `health_check()` retorna `connected: true` para System User token
- [ ] Status `delivered` → DB actualizada + evento emitido

### Fase 2

- [ ] `POST /api/templates` crea template en DB + Meta API
- [ ] `GET /api/templates` lista templates con status de aprobación
- [ ] `send_template()` envía template aprobado correctamente
- [ ] 24h window: texto libre dentro, template fuera
- [ ] LTO template muestra countdown + botón copiar
- [ ] `python3 -m pytest tests/ -v` — todos pasan
- [ ] `alembic upgrade head` — sin errores

### Fase 3

- [ ] `send_image()` envía imagen con caption
- [ ] Catálogo tiene `image_url` → LLM puede mostrar imagen
- [ ] `show_category_menu` envía lista nativa → selección → agregar al carrito
- [ ] `python3 -m pytest tests/ -v` — todos pasan

### Fase 4

- [ ] `delivered` → scheduled follow-up creado
- [ ] Scheduler envía follow-up al tiempo correcto
- [ ] Cita creada → reminder programado 24h antes
- [ ] Re-engagement para conversaciones > 7 días inactivas
- [ ] `python3 -m pytest tests/ -v` — todos pasan

---

## Dependencias entre Fases

```
Fase 1.1 (health check fix) ← independiente
Fase 1.2 (tool names fix)    ← independiente
Fase 1.3 (interactive buttons) ← 1.3.1 + 1.3.3 antes de 1.3.4
Fase 1.4 (status webhook)   ← independiente, pero Fase 4.1 necesita 1.4

Fase 2.1 (META_APP_ID)      ← necesita Fase 1.1.1 (ya hecho ahí)
Fase 2.2 (template mgmt)    ← necesita 2.1
Fase 2.3 (template sending) ← necesita 2.2 + 1.3.1
Fase 2.4 (LTO)              ← necesita 2.3

Fase 3.1 (images)           ← parcialmente necesita 2.3
Fase 3.2 (list messages)    ← necesita 1.3.2

Fase 4.1 (follow-up)        ← necesita 1.4 + 2.3
Fase 4.2 (scheduled)        ← necesita 4.1 + 2.3
```

---

## Riesgos y Mitigaciones

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Meta rechaza templates | Alto | Fallback a texto libre dentro de ventana. Templates genéricos se aprueban más fácil |
| `/debug_token` cambia comportamiento | Bajo | Fallback a `/me/permissions` ya cubre |
| Interactive buttons limitados a 3 | Medio | Usar list messages (hasta 10 opciones) para catálogos |
| Rate limiting de Meta API al crear templates | Bajo | Throttle en template creation endpoint |
| Image URLs rotas en catálogo | Medio | Validar URL al guardar. Fallback a texto sin imagen |
| 24h window edge case | Bajo | Usar `< 86400` (estricto menor) para evitar off-by-one |

---

## Orden de Implementación (Recomendado)

```
Día 1: 1.1 (health check) + 1.2 (tool names) + 1.3.1-1.3.3 (meta client buttons + webhook parsing)
Día 2: 1.3.4 (HITL integration) + 1.4 (status webhook)
Día 3-4: 2.1-2.3 (templates: config + management + sending)
Día 5: 2.4 (LTO) + tests de integración
Día 6-7: 3.1-3.2 (images + list messages)
Día 8-9: 4.1-4.2 (follow-up + scheduled messages)
Día 10: Testing end-to-end + deploy
```

Total estimado: **10 días hábiles** para las 4 fases.

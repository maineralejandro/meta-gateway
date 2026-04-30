# ⏰ Plan de Implementación: Sesiones con Timeout

Este plan transforma la conversación eterna por número de teléfono en un sistema basado en **sesiones lógicas** con expiración automática por inactividad.

---

## Fase 1: Infraestructura de Datos

**Objetivo:** Crear la tabla `sessions` y agregar columnas de sesión a las tablas existentes.

1.  **Crear migración `db/migrations/002_sessions.sql`**:
    ```sql
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        phone TEXT NOT NULL,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ended_at TIMESTAMP,
        end_reason TEXT,    -- 'timeout', 'manual', 'resolved'
        summary TEXT,
        message_count INTEGER DEFAULT 0,
        FOREIGN KEY (phone) REFERENCES conversations(phone)
    );

    CREATE INDEX IF NOT EXISTS idx_sessions_phone ON sessions(phone, started_at);
    ```
    *   **NO usar ALTER TABLE** para agregar `session_id` a `messages` ni `current_session_id` a `conversations` en esta fase. SQLite maneja ALTER TABLE de forma limitada. En su lugar, agregar estas columnas directamente al `schema.sql` para nuevas instalaciones, y crear queries que manejen la ausencia de la columna en datos existentes.

2.  **Modificar `db/schema.sql`**:
    *   Agregar la tabla `sessions` (el mismo SQL de arriba) **antes** de la tabla `messages`.
    *   Agregar `current_session_id TEXT` a la tabla `conversations` (línea 22, antes de `created_at`).
    *   Agregar `session_id TEXT` a la tabla `messages` (línea 35, antes de `created_at`).
    *   Agregar los índices correspondientes.

3.  **Modificar `db/models.py`**:
    *   Crear el dataclass `Session`:
    ```python
    @dataclass
    class Session:
        id: str
        phone: str
        started_at: Optional[str] = None
        ended_at: Optional[str] = None
        end_reason: Optional[str] = None
        summary: Optional[str] = None
        message_count: int = 0
    ```
    *   Agregar `row_to_session(row)` siguiendo el patrón de las funciones existentes (`row_to_conversation`, etc.).
    *   Agregar `current_session_id: Optional[str] = None` al dataclass `Conversation` (línea 28, después de `agent_id`).
    *   Agregar `session_id: Optional[str] = None` al dataclass `Message` (línea 41, después de `meta_message_id`).

4.  **Modificar `db/database.py`**:
    *   Actualizar `row_to_conversation` en `get_conversation()` y `get_all_conversations()` para incluir `current_session_id` en el SELECT (líneas 67-68 y 76-77).
    *   Actualizar `row_to_message` en `get_messages()` para incluir `session_id` en el SELECT (línea 84).
    *   Agregar nuevos métodos a la clase `Database`:
    ```python
    async def create_session(self, phone: str) -> str:
        """Crea una nueva sesión y retorna su ID."""
        import uuid
        session_id = str(uuid.uuid4())
        conn = await self._get_conn()
        await conn.execute(
            "INSERT INTO sessions (id, phone) VALUES (?, ?)",
            (session_id, phone),
        )
        await conn.execute(
            "UPDATE conversations SET current_session_id=? WHERE phone=?",
            (session_id, phone),
        )
        await conn.commit()
        return session_id

    async def get_active_session(self, phone: str) -> Session | None:
        row = await self.fetchone(
            "SELECT * FROM sessions WHERE phone=? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            (phone,),
        )
        return row_to_session(row)

    async def close_session(self, session_id: str, reason: str, summary: str = None):
        await self.execute(
            "UPDATE sessions SET ended_at=CURRENT_TIMESTAMP, end_reason=?, summary=? WHERE id=?",
            (reason, summary, session_id),
        )
        await self.commit()

    async def increment_session_message_count(self, session_id: str):
        await self.execute(
            "UPDATE sessions SET message_count = message_count + 1 WHERE id=?",
            (session_id,),
        )
        await self.commit()
    ```

---

## Fase 2: Lógica de Gestión de Sesiones

**Objetivo:** Implementar la regla de negocio de expiración por inactividad.

1.  **Crear `core/sessions.py`**:
    *   Definir constante `SESSION_TIMEOUT_HOURS = 4`.
    *   Implementar la clase `SessionManager`:
    ```python
    from datetime import datetime, timedelta, timezone
    from db.database import db
    import structlog

    logger = structlog.get_logger()
    SESSION_TIMEOUT_HOURS = 4

    class SessionManager:
        async def get_or_create_session(self, phone: str) -> str:
            """Retorna el session_id activo o crea uno nuevo si expiró."""
            conv = await db.get_conversation(phone)

            if not conv:
                # Conversación nueva, se crea en webhook.py antes de llamar aquí
                return await db.create_session(phone)

            if not conv.current_session_id:
                # Conversación existente sin sesión (datos legacy)
                return await db.create_session(phone)

            # Verificar timeout
            if conv.last_message_at:
                last_msg_time = datetime.fromisoformat(conv.last_message_at)
                elapsed = datetime.now(timezone.utc) - last_msg_time
                if elapsed > timedelta(hours=SESSION_TIMEOUT_HOURS):
                    # Cerrar sesión vieja
                    await db.close_session(
                        conv.current_session_id,
                        reason='timeout',
                    )
                    logger.info(
                        "session_expired",
                        phone=phone,
                        old_session=conv.current_session_id,
                        hours_inactive=elapsed.total_seconds() / 3600,
                    )
                    # Resetear estado a BOT_ACTIVE si estaba escalado
                    if conv.state != "BOT_ACTIVE":
                        await db.execute(
                            "UPDATE conversations SET state='BOT_ACTIVE', requires_human_review=0 WHERE phone=?",
                            (phone,),
                        )
                        await db.commit()
                    return await db.create_session(phone)

            return conv.current_session_id

    session_manager = SessionManager()
    ```

> [!IMPORTANT]
> **Manejo de timezone**: `last_message_at` viene de SQLite como `CURRENT_TIMESTAMP` que es UTC. Al comparar, asegurarse de usar `datetime.now(timezone.utc)`. Si SQLite devuelve un string naive, parsearlo y asumir UTC.

---

## Fase 3: Integración en el Flujo de Mensajes

**Objetivo:** Vincular cada mensaje entrante y saliente a la sesión activa.

1.  **Modificar `routers/webhook.py`**:
    *   Importar `session_manager` desde `core.sessions`.
    *   Después de crear/verificar la conversación (línea 74, después del `if not row` / `else`) y **antes** de insertar el mensaje (línea 79), agregar:
    ```python
    session_id = await session_manager.get_or_create_session(phone)
    ```
    *   Modificar la query de inserción de mensaje (línea 80) para incluir `session_id`:
    ```python
    ("INSERT INTO messages (phone, direction, source, text, media_type, media_url, meta_message_id, session_id) VALUES (?, 'inbound', 'customer', ?, ?, ?, ?, ?)",
     (phone, text, media_type, media_url, meta_msg_id, session_id)),
    ```
    *   Agregar el incremento del contador de la sesión:
    ```python
    await db.increment_session_message_count(session_id)
    ```

2.  **Modificar `core/hitl_router.py`**:
    *   En `process_inbound_message()`, al insertar mensajes de respuesta del bot (líneas 108-111 y 137-140), agregar `session_id` al INSERT:
    ```python
    # Obtener session_id activa
    conv = await db.get_conversation(phone)
    session_id = conv.current_session_id if conv else None

    cursor = await conn.execute(
        "INSERT INTO messages (phone, direction, source, text, session_id) VALUES (?, 'outbound', 'bot', ?, ?)",
        (phone, response_text, session_id),
    )
    ```
    *   **Nota**: `conv` ya se obtiene en línea 61, reutilizar esa variable y su `current_session_id`.

3.  **Modificar `routers/messages.py`**:
    *   En `send_message()` (línea 30), agregar `session_id` al INSERT del mensaje humano:
    ```python
    # Obtener session_id
    conv_row = await db.fetchone("SELECT current_session_id FROM conversations WHERE phone=?", (req.phone,))
    session_id = conv_row["current_session_id"] if conv_row else None

    ("INSERT INTO messages (phone, direction, source, text, session_id) VALUES (?, 'outbound', 'human', ?, ?)",
     (req.phone, req.message, session_id)),
    ```

---

## Fase 4: Endpoint de Cierre Manual

**Objetivo:** Permitir al operador cerrar sesiones desde el dashboard.

1.  **Modificar `routers/conversations.py`**:
    *   Agregar endpoint `POST /api/conversations/{phone}/close-session`:
    ```python
    @router.post("/{phone}/close-session")
    async def close_session(phone: str):
        db = await get_db()
        conv = await db.get_conversation(phone)
        if not conv or not conv.current_session_id:
            return {"status": "no_active_session"}
        
        await db.close_session(conv.current_session_id, reason='manual')
        
        # Resetear a BOT_ACTIVE
        await db.execute_transaction([
            ("UPDATE conversations SET state='BOT_ACTIVE', requires_human_review=0, current_session_id=NULL WHERE phone=?",
             (phone,)),
        ])
        
        await manager.send_to_all({
            "type": "session-closed",
            "phone": phone,
            "reason": "manual",
        })
        
        logger.info("session_closed_manually", phone=phone)
        return {"status": "ok"}
    ```

---

## Fase 5: Pruebas

1.  **Crear `tests/test_sessions.py`**:
    *   **Test de creación**: Verificar que `get_or_create_session` crea una sesión nueva para un teléfono sin sesión.
    *   **Test de reutilización**: Verificar que llamar dos veces seguidas retorna el mismo `session_id`.
    *   **Test de timeout**: Insertar una conversación con `last_message_at` de hace 5 horas, verificar que `get_or_create_session` cierre la sesión vieja y cree una nueva.
    *   **Test de reset de estado**: Verificar que al expirar una sesión de una conversación en `HUMAN_ONLY`, el estado vuelva a `BOT_ACTIVE`.
    *   **Test de cierre manual**: Llamar al endpoint `/close-session`, verificar que la sesión se cierre y el estado se resetee.

2.  **Migración de datos existentes**:
    *   Las conversaciones existentes sin `current_session_id` serán manejadas por el `if not conv.current_session_id` en `SessionManager.get_or_create_session()`, que crea una sesión nueva automáticamente en el primer mensaje post-migración.

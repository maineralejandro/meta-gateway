# 6c: Turn-Based Conversation Model — Plan de Implementacion

## Problemas a resolver

### Problema 1: El historial contiene mensajes que aun no han ocurrido conversacionalmente

`build_context()` lee los ultimos 16 mensajes de `messages` sin distinguir cuales ya
fueron respondidos por el bot. Si M1 (inbound) esta en DB pero el bot aun no respondio,
M1 aparece en el historial como un turno de usuario sin respuesta — violando la regla
`user/assistant/user/assistant`.

### Problema 2: El sistema no sabe que un burst es una sola intencion del cliente

Cada mensaje inbound dispara un `process_inbound_message()` independiente. Tres mensajes
en 10s generan 3 llamadas al LLM, 3 respuestas, y un historial con 3 `user` consecutivos
que la API rechaza con error 400.

## Diseno: Event Sourcing aplicado a conversaciones

### Dos capas

| Capa | Tabla | Proposito | Quien la lee |
|------|-------|-----------|-------------|
| **Event Log** | `messages` (existente) | Registro append-only de todo lo que llega. Crudo, inmutable. | Dashboard, auditoria |
| **Conversation State** | `turns` (nueva) | Turnos completados. Solo existe user+assistant pareados. | `build_context()` |

**La regla**: un mensaje no existe para el LLM hasta que el bot haya respondido a el.

### Flujo nuevo

```
Meta Webhook POST
  → webhook.py: save message to messages (Event Log)
  → TurnBuilder.debounce(phone, text, correlation_id, message_id)
    → acumula en buffer en memoria
    → 2s de silencio → turno del usuario completo
  → hitl_router.process_turn(phone, consolidated_text, correlation_id, message_ids)
    → build_context() lee turns (NO messages)
    → inference_engine.generate()
    → response
    → save outbound to messages
    → save turn to turns table (user_text + assistant_text)
```

## Decisiones de diseno

| Decision | Eleccion | Rationale |
|----------|----------|-----------|
| Donde vive el debounce | **Capa independiente: `core/turn_builder.py`** | Separa responsabilidades, no acopla al webhook ni al hitl_router |
| Debounce window | **2 segundos desde el ultimo mensaje** | Timer que se resetea con cada mensaje nuevo. Captura el 95% de bursts naturales de WhatsApp |
| Formato de consolidacion | `[1] Hola\n\n[2] Quiero un completo\n\n[3] Con todo` | Doble newline entre mensajes. Comunica al LLM: unidades discretas, orden temporal, mismo turno |
| Tabla de turnos | **`turns` nueva tabla** | No altera `messages`. `build_context()` lee `turns`, no `messages` |
| Seguridad | **`_normalize_roles()` como safety net** | Post-validacion del array de mensajes antes de enviar al LLM |

## Steps de implementacion

### T0: Migration `013_turns_table.sql`

Crear tabla `turns`:

```sql
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    user_correlation_id TEXT,
    assistant_correlation_id TEXT,
    message_ids TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

CREATE INDEX IF NOT EXISTS idx_turns_phone_created ON turns(phone, created_at DESC);
```

**Campos**:
- `user_text`: texto consolidado del turno del usuario (`[1] Hola\n\n[2] Quiero un completo`)
- `assistant_text`: respuesta del bot
- `user_correlation_id` / `assistant_correlation_id`: tracing
- `message_ids`: JSON array de IDs de mensajes del burst (para auditoria)

**Migrator count**: 12 → 13

### T1: Model `Turn` en `db/models.py`

```python
@dataclass
class Turn:
    id: int | None = None
    phone: str = ""
    user_text: str = ""
    assistant_text: str = ""
    user_correlation_id: str | None = None
    assistant_correlation_id: str | None = None
    message_ids: str = "[]"
    created_at: str | None = None
```

+ `row_to_turn()` factory function.

### T2: DB methods en `db/database.py`

| Metodo | Query | Retorna |
|--------|-------|---------|
| `insert_turn(turn: Turn) -> int` | INSERT | lastrowid |
| `get_turns(phone, limit=16) -> list[Turn]` | SELECT ... ORDER BY created_at DESC LIMIT | turnos recientes (reversed en caller) |
| `count_turns(phone) -> int` | SELECT COUNT(*) | cantidad de turnos |
| `get_last_turn(phone) -> Turn \| None` | SELECT ... ORDER BY created_at DESC LIMIT 1 | ultimo turno |

`get_turns()` reemplaza a `get_messages()` como fuente de `build_context()`.

### T3: `core/turn_builder.py` — Capa de debounce

Nueva clase `TurnBuilder`:

```python
@dataclass
class BufferedMessage:
    text: str
    correlation_id: str
    message_id: int
    received_at: float


class TurnBuilder:
    _buffers: dict[str, list[BufferedMessage]]  # phone → mensajes pendientes
    _timers: dict[str, asyncio.Task]             # phone → debounce timer task
    DEBOUNCE_SECONDS = 2.0

    async def debounce(self, phone, text, correlation_id, message_id):
        1. Agregar (text, correlation_id, message_id, timestamp) a _buffers[phone]
        2. Cancelar timer anterior si existe (_timers[phone].cancel())
        3. Crear nuevo asyncio.create_task(_fire_after_silence(phone, 2.0))

    async def _fire_after_silence(self, phone, delay):
        1. await asyncio.sleep(delay)
        2. Tomar todos los mensajes de _buffers[phone]
        3. Limpiar _buffers[phone] y _timers[phone]
        4. Consolidar texto: "[1] Hola\n\n[2] Quiero un completo\n\n[3] Con todo"
        5. Extraer correlation_id del primer mensaje (o generar uno)
        6. Recopilar message_ids como lista
        7. Llamar hitl_router.process_turn(phone, consolidated, correlation_id, message_ids)

    async def flush(self, phone):
        — Para testing: fuerza emision inmediata sin esperar 2s
```

**Singleton**: `turn_builder = TurnBuilder()`

### T4: Modificar `routers/webhook.py`

En `_receive_webhook_inner()`, reemplazar la linea:

```python
track_task(asyncio.create_task(_safe_process(phone, text, correlation_id=correlation_id)))
```

por:

```python
await turn_builder.debounce(phone, text, correlation_id, message_id)
```

Donde `message_id` es el retorno de `db.insert_message()` (que ya se llama antes).

**Nota**: `debounce()` es async pero no bloquea — programa el timer y retorna
inmediatamente. El webhook response `{"status": "processing"}` se devuelve sin
esperar el turno completo.

**`_safe_process()`** se elimina del webhook (se mueve la logica a
`hitl_router.process_turn()`).

### T5: Modificar `core/hitl_router.py` — `process_turn()`

Nuevo metodo `process_turn()` que reemplaza el flujo actual:

```python
async def process_turn(self, phone, consolidated_text, correlation_id, message_ids):
    lock = _get_phone_lock(phone)
    async with lock:
        await self._process_turn_inner(phone, consolidated_text, correlation_id, message_ids)
```

Diferencias con `_process_inbound_message_inner()`:

1. Recibe `consolidated_text` en vez de texto individual
2. Recibe `message_ids` (lista de IDs del burst)
3. Llama a `memory_manager.build_context(phone, current_message=consolidated_text, ...)`
4. Despues de la respuesta del bot, **guarda el turno** en `turns`:

```python
await db.insert_turn(Turn(
    phone=phone,
    user_text=consolidated_text,
    assistant_text=response_text,
    user_correlation_id=correlation_id,
    assistant_correlation_id=correlation_id,
    message_ids=json.dumps(message_ids),
))
```

5. Mantiene el `insert_message(direction="outbound")` para el Event Log

**`process_inbound_message()`** se marca como deprecated pero se mantiene por
compatibilidad (redirige a `process_turn()` con un solo mensaje).

### T6: Modificar `core/memory.py` — `build_context()` lee turns

Reescribir `build_context()`:

```python
async def build_context(self, phone, current_message=None, agent_id=None, capabilities=None):
    memory = await db.get_memory(phone)
    recent_turns = await db.get_turns(phone, limit=WINDOW_SIZE, desc=True)
    recent_turns = list(reversed(recent_turns))

    context = []

    # Summary injection (1 system message)
    if memory and memory.summary:
        summary_text = f"Resumen de la conversacion anterior:\n{memory.summary}"
        if memory.key_facts and memory.key_facts != "[]":
            summary_text += f"\nDatos clave del cliente: {memory.key_facts}"
        context.append({"role": "system", "content": summary_text})

    # Capability context (system messages)
    resolved = capabilities if capabilities is not None else await capability_registry.resolve(agent_id)
    for cap in resolved:
        cap_context = await cap.format_for_context(phone, cap.config)
        if cap_context:
            context.append({"role": "system", "content": cap_context})

    # Turn history (user/assistant alternating by design)
    for turn in recent_turns:
        user_text = self._format_turn_user_text(turn.user_text)
        if user_text:
            context.append({"role": "user", "content": user_text})
            context.append({"role": "assistant", "content": turn.assistant_text})

    return context
```

**Cambios clave**:
- Lee `turns` en vez de `messages` → garantiza alternancia user/assistant por diseno
- No necesita dedup de `current_message` — el mensaje pendiente no esta en `turns` aun
- `_format_turn_user_text()`: filtra turns que son solo media (`[image]`, etc.)
- `WINDOW_SIZE` ahora cuenta turnos (16 turnos = 32 mensajes), no mensajes individuales

### T7: Modificar `core/inference.py` — `_normalize_roles()` safety net

Agregar funcion `_normalize_roles()` que se ejecuta sobre `messages` antes de enviar
al LLM:

```python
def _normalize_roles(messages: list[dict]) -> list[dict]:
    """Safety net: ensure role alternation for OpenAI API compliance."""
    normalized = []
    for msg in messages:
        if not normalized:
            normalized.append(msg)
            continue

        last_role = normalized[-1]["role"]

        # Merge consecutive same-role messages
        if msg["role"] == last_role and msg["role"] in ("user", "assistant"):
            normalized[-1]["content"] += "\n" + msg["content"]
            continue

        # Skip system messages after the first (merge into first system)
        if msg["role"] == "system" and last_role == "system":
            normalized[-1]["content"] += "\n\n" + msg["content"]
            continue

        # Ensure user follows assistant and vice versa
        if msg["role"] == "user" and last_role == "user":
            normalized[-1]["content"] += "\n" + msg["content"]
            continue
        if msg["role"] == "assistant" and last_role == "assistant":
            normalized[-1]["content"] += "\n" + msg["content"]
            continue

        normalized.append(msg)

    return normalized
```

En `generate()`, antes de `trace["request_messages"] = json.dumps(messages)`:

```python
messages = _normalize_roles(messages)
```

### T8: Ajustar `maybe_summarize()` para contar turns

`maybe_summarize()` actualmente cuenta mensajes individuales. Se ajusta para contar
turnos:

```python
total = await db.count_turns(phone)
# ... resto igual pero formatea turns en vez de mensajes
```

### T9: Tests unitarios

Nuevo archivo `tests/test_turn_builder.py`:

| Test | Que valida |
|------|-----------|
| `test_single_message_fires_after_debounce` | 1 mensaje → 2s → turno se emite |
| `test_burst_consolidates` | 3 mensajes en 1s → 1 solo turno consolidado |
| `test_consolidation_format` | Formato `[1] Hola\n\n[2] Quiero un completo\n\n[3] Con todo` |
| `test_timer_resets_on_new_message` | M1 → timer 2s → M2 antes de 2s → timer se resetea |
| `test_flush_immediate` | `flush()` emite sin esperar debounce |
| `test_empty_buffer_noop` | `flush()` en buffer vacio no hace nada |
| `test_different_phones_independent` | Mensajes de telefonos distintos no se mezclan |

Modificar `tests/test_memory.py`:

| Test | Cambio |
|------|--------|
| `test_build_context_no_memory` | Insertar en `turns` en vez de `messages` |
| `test_build_context_returns_recent_messages` | Idem — validar alternancia user/assistant |
| `test_build_context_excludes_current_message` | YA NO NECESARIO — turns no contiene pending. Simplificar. |
| `test_build_context_with_memory` | Idem |
| `test_build_context_filters_media` | Ajustar para turns con media |
| `test_build_context_guarantees_alternation` | **NUEVO** — validar que nunca hay 2 roles consecutivos iguales |
| `test_build_context_includes_order_state` | Idem — usar turns |

Nuevo archivo `tests/test_normalize_roles.py`:

| Test | Que valida |
|------|-----------|
| `test_consecutive_user_merged` | 2 user seguidos → merge |
| `test_consecutive_assistant_merged` | 2 assistant seguidos → merge |
| `test_consecutive_system_merged` | 2 system seguidos → merge |
| `test_alternating_unchanged` | user/assistant/user → sin cambios |
| `test_empty_input` | lista vacia → lista vacia |

Actualizar `tests/test_migrator.py`:
- Count esperado: 12 → 13

### T10: E2E pipeline test con burst

En `tests/test_e2e_pipeline.py` o nuevo `tests/test_e2e_turns.py`:

| Test | Que valida |
|------|-----------|
| `test_burst_three_messages_single_llm_call` | 3 mensajes rapidos → 1 solo LLM call → 1 respuesta |
| `test_turn_based_history_no_400` | Historial de turnos → no error 400 de la API |
| `test_normalize_roles_catches_edge_case` | Forzar edge case → `_normalize_roles()` lo corrige |

## Cambios por archivo

| Archivo | Tipo | Descripcion |
|---------|------|-------------|
| `db/migrations/013_turns_table.sql` | **Nuevo** | Tabla turns + index |
| `db/models.py` | Modificar | +`Turn` dataclass + `row_to_turn()` |
| `db/database.py` | Modificar | +`insert_turn()`, `get_turns()`, `count_turns()`, `get_last_turn()` |
| `core/turn_builder.py` | **Nuevo** | `TurnBuilder` con debounce 2s, buffer per-phone, consolidacion |
| `core/hitl_router.py` | Modificar | +`process_turn()`, deprecar `process_inbound_message()` |
| `core/memory.py` | Modificar | `build_context()` lee `turns` en vez de `messages` |
| `core/inference.py` | Modificar | +`_normalize_roles()` safety net |
| `routers/webhook.py` | Modificar | Reemplazar `_safe_process` → `turn_builder.debounce()` |
| `tests/test_turn_builder.py` | **Nuevo** | 7 tests de debounce y consolidacion |
| `tests/test_normalize_roles.py` | **Nuevo** | 5 tests del safety net |
| `tests/test_memory.py` | Modificar | Adaptar a turns-based context |
| `tests/test_migrator.py` | Modificar | Count 12 → 13 |

## Lo que NO cambia

- **`messages` table**: Sigue existiendo como Event Log. El webhook sigue insertando cada
  mensaje individual. El dashboard sigue leyendo de `messages`.
- **`conversation_memory`**: El summary sigue inyectandose como system message.
  `maybe_summarize()` se ajusta para contar turns pero la logica es la misma.
- **Capabilities**: `format_for_context()` y `parse_tags()` no cambian.
- **Sentiment analysis**: Se sigue ejecutando por turno (no por mensaje individual). Con
  bursts, el sentimiento se analiza sobre el texto consolidado — que es mas representativo
  de la intencion real.
- **Dashboard**: Lee de `messages` (Event Log) para mostrar conversaciones. No necesita
  cambios para mostrar mensajes individuales.

## Orden de ejecucion

Los steps T0→T10 se ejecutan en orden porque cada uno depende del anterior:

1. T0 (migration) → T1 (model) → T2 (db methods) son la base de datos
2. T3 (turn_builder) es la nueva logica central
3. T4 (webhook) + T5 (hitl_router) + T6 (memory) son las integraciones
4. T7 (normalize_roles) es el safety net
5. T8 (summarize) es ajuste menor
6. T9 + T10 son validacion

## Criterios de exito

1. **Error 400 eliminado**: `inference_traces` con `response_source='error'` y
   `error_type='BadRequestError'` = 0 despues del deploy
2. **Burst → 1 LLM call**: 3 mensajes en 2s generan exactamente 1 `inference_traces` row
3. **Role alternation garantizada**: `request_messages` en traces muestra
   `user/assistant/user/assistant` sin excepcion
4. **Debounce < 2s perceptible**: El usuario no percibe delay adicional vs. el sistema
   actual (el tiempo de inferencia domina)
5. **333+ tests pasando**: Los tests existentes se adaptan + 12 nuevos tests = 333+ total

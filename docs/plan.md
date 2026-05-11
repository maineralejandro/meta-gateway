# Plan: Sistema de Agentes Dinámicos (Sin Hardcoding de Prompts)

## Fase 1 — Tabla `agents` + Modelo

### Nuevos archivos:
- `db/migrations/001_agents.sql`

### Modificar:
- `db/schema.sql` — agregar tabla `agents`
- `db/models.py` — agregar dataclass `Agent`
- `db/database.py` — agregar `get_agent()`, `get_all_agents()`, `upsert_agent()`

### Tabla `agents`:
```sql
CREATE TABLE IF NOT EXISTS agents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  system_prompt TEXT NOT NULL,
  escalation_marker TEXT NOT NULL DEFAULT 'ESCALATE_TO_HUMAN',
  fallback_responses TEXT NOT NULL DEFAULT '{}',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- **fallback_responses**: JSON string con las respuestas del `_fallback_response` actual (keys: `price`, `promo`, `delivery`, `greeting`, `default`).
- **is_active**: flag para habilitar/deshabilitar sin borrar.
- **Semilla**: 1 `INSERT` con los datos actuales del `SYSTEM_PROMPT` hardcoded (migración sin pérdida).

---

## Fase 2 — InferenceEngine lee desde DB

### Modificar:
- `core/inference.py`

### Cambios:
- `InferenceEngine.__init__()` → recibe `agent_id: int | None = None`.
- **Nueva propiedad `_load_prompt()`**: consulta `agents` table. Si `agent_id` dado, lo usa; si no, usa el agent `is_active=1` más reciente.
- `generate()` → en vez de `SYSTEM_PROMPT` fijo, usa `self._load_prompt()`. Cachea en `self._current_prompt` + `self._prompt_loaded_at`. **TTL de cache = 60s** (permite cambios en caliente sin reiniciar).
- **ESCALATION_MARKER** → lo saca del agent en DB (campo `escalation_marker`).
- `_fallback_response()` → parsea `fallback_responses` JSON del agent en DB, usa esas respuestas en vez de las hardcoded.
- `_reload_prompt()` → fuerza recarga (para uso desde API).

---

## Fase 3 — API CRUD de Agents

### Nuevo archivo:
- `routers/agents.py`

### Endpoints:

| Método | Ruta | Descripción |
| :--- | :--- | :--- |
| GET | `/api/agents` | Lista todos los agents |
| GET | `/api/agents/{id}` | Detalle de un agent |
| POST | `/api/agents` | Crear agent |
| PUT | `/api/agents/{id}` | Modificar agent |
| POST | `/api/agents/{id}/activate` | Activar agent (desactiva los demás) |
| POST | `/api/agents/{id}/reload` | Forzar recarga del prompt en InferenceEngine |

### Schemas (Pydantic):
- `AgentCreate(name, description, system_prompt, escalation_marker, fallback_responses)`
- `AgentUpdate(description?, system_prompt?, escalation_marker?, fallback_responses?)` — todos opcionales
- `AgentResponse` — igual al modelo + id

### Modificar:
- `main.py` — `app.include_router(agents.router)`
- `core/inference.py` — `inference_engine` ahora es función/lazy para poder recibir `agent_id` dinámicamente.

---

## Fase 4 — Dashboard: UI de edición de Agent

### Modificar:
- `dashboard/pages/index.tsx` — agregar tab/panel de "Agente"

### Nuevos componentes:
- `dashboard/components/AgentEditor.tsx` — textarea para `system_prompt`, campos para `name`/`description`, JSON editor para `fallback_responses`, botón guardar, botón activar.

### Flujo:
1. Carga agent activo vía `GET /api/agents?is_active=1`
2. Textarea editable para `system_prompt`
3. Botón "Guardar" → `PUT /api/agents/{id}`
4. Botón "Activar" → `POST /api/agents/{id}/activate` + `POST /api/agents/{id}/reload`
5. Selector para cambiar entre agents existentes
6. Botón "Nuevo Agente" → `POST /api/agents`

---

## Fase 5 — Multi-agente por conversación

### Modificar:
- `db/schema.sql` — agregar columna `agent_id INTEGER DEFAULT 1` a `conversations`
- `db/models.py` — agregar `agent_id` a `Conversation`
- `core/hitl_router.py` — `process_inbound_message()` pasa `conversation.agent_id` a `inference_engine.generate()`
- `core/inference.py` — `generate(user_message, history, agent_id=None)` → si `agent_id`, carga ese agent específico.
- `routers/conversations.py` — endpoint para cambiar agent de una conversación.

> [!NOTE]
> Esto permite: 1 bot para food truck, otro bot para una tienda, etc., cada conversación con su propio agent.

---

## Orden de ejecución estricto

1. **Fase 1** → Tabla + modelo + seed data (sin esto, nada funciona)
2. **Fase 2** → InferenceEngine lee DB (sin esto, el bot no funciona con datos nuevos)
3. **Fase 3** → API CRUD (sin esto, no hay forma de editar agents)
4. **Fase 4** → Dashboard UI (sin esto, solo curl puede editar)
5. **Fase 5** → Multi-agente (feature avanzado, puede ir después)

> [!IMPORTANT]
> Cada fase es auto-contenida y probable independiente. Fases 1-3 son el MVP (resolver el problema original). Fase 4 es UX. Fase 5 es escalabilidad.

---

## Notas para el agente implementador

- **Seed data obligatoria**: el `INSERT` del agent actual con el `SYSTEM_PROMPT` que está hoy hardcoded en `inference.py:7-42` y los `_fallback_response` de `inference.py:92-102`. Esto garantiza zero-downtime.
- **Cache TTL**: 60 segundos en `InferenceEngine`. No hacer reload por cada mensaje (evita una llamada DB extra por request).
- **fallback_responses**: guardar como JSON string en DB. Keys: `price`, `promo`, `delivery`, `greeting`, `default`. El `_fallback_response` actual mapea directo.
- **Tests**: actualizar `tests/test_api.py` con tests de los endpoints CRUD de agents. Agregar `tests/test_inference.py` que verifique que `generate()` usa el prompt desde DB.
- **No romper hitl_router.py**: sigue importando `inference_engine` como singleton. El engine internamente resuelve qué agent usar.
- **conversations table ya existente**: para Fase 5, usar `ALTER TABLE` en migración, no recrear la tabla.
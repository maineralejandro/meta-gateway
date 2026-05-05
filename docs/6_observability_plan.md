# P0: Observabilidad y Diagnostico — Plan de Implementacion

## Problema raiz confirmado con datos de produccion

La DB de produccion muestra que el 4 de mayo:
- 5+ mensajes inbound recibidos entre 14:52 y 16:19
- Solo **1 outbound** registrado (mensaje 196 a las 16:19)
- Solo **1 decision** guardada (para ese unico mensaje)
- Los mensajes "🤔 No estoy seguro" que el usuario vio en WhatsApp **NO estan en la DB**

Esto confirma que el LLM esta fallando con excepcion (Path B), no con fallback silencioso (Path A).
El `raise` en `hitl_router.py:124` envia la excepcion al `_safe_process` del webhook, que envia
un mensaje generico por Meta API pero **no lo guarda en la DB** ni genera una decision.

## Brechas de observabilidad identificadas

| # | Brecha | Impacto | Severidad |
|---|--------|---------|-----------|
| 1 | **Fallback silencioso** — `_llm.available == False` no loggea nada | Imposible saber si la API key es invalida | Critica |
| 2 | **Excepcion del LLM no persiste** — Path B no guarda mensaje ni decision en DB | Datos perdidos, metricas falsas | Critica |
| 3 | **No se distingue fallback de LLM real** — `agent_decisions` no tiene `response_source` | Imposible medir calidad del LLM | Alta |
| 4 | **correlation_id roto** — webhook y processing usan IDs distintos, no persistidos | Imposible rastrear un request end-to-end | Alta |
| 5 | **No hay log file** — solo stderr, se pierden al reiniciar uvicorn | Diagnostico post-mortem imposible | Alta |
| 6 | **No hay endpoint de diagnostico** — no se puede inspeccionar estado sin acceso a DB/consola | Debugging lento y manual | Media |
| 7 | **No se almacena prompt ni respuesta cruda** — imposible reproducir errores | Imposible saber que vio el LLM | Media |
| 8 | **Metrica `llm_errors` no cuenta fallbacks internos** — metricas de error incompletas | Dashboard miente | Media |

## Componentes del P0

### P0-A: Inference tracing (persiste prompts y respuestas)

**Nueva tabla**: `inference_traces`

```sql
CREATE TABLE IF NOT EXISTS inference_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    agent_id INTEGER,
    request_messages TEXT NOT NULL,    -- JSON: messages array enviado al LLM
    response_raw TEXT,                  -- respuesta cruda del LLM (antes de parse_tags)
    response_source TEXT NOT NULL,      -- 'llm' | 'fallback' | 'error'
    error_type TEXT,                    -- tipo de excepcion si hubo error
    error_message TEXT,                 -- mensaje de error
    token_usage_prompt INTEGER DEFAULT 0,
    token_usage_completion INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Cambios en `inference.py`**:
- `generate()` retorna `tuple[str, bool, dict]` — el 3er elemento es un trace dict con
  `source`, `error`, `tokens`, `latency`
- Cuando `_llm.available == False`: loggear WARNING + retornar trace con `source='fallback'`
- Cuando hay excepcion: incluir `error_type` y `error_message` en trace
- Cuando LLM responde OK: incluir `response_raw` y `tokens` en trace
- Guardar trace en DB despues de cada llamada

### P0-B: Fix del Path B — persistir mensajes de error

**Cambios en `hitl_router.py`**:

El flujo actual tiene dos paths de error:

**Path A** (interno a `inference.py`):
- `generate()` atrapa excepcion → retorna `(fallback_text, False)`
- `hitl_router` continua normalmente → parse_tags → send → save
- Resultado: mensaje guardado en DB, decision guardada
- Problema: imposible distinguir fallback de LLM real

**Path B** (excepcion escapa de `generate()`):
- Esto NO deberia pasar porque `generate()` tiene `except Exception`
- PERO: si `sentiment_analyzer.analyze()` o `memory_manager.build_context()` fallan
  ANTES de llegar a inference, la excepcion sube al `except Exception` de la linea 198
- El `_safe_process` del webhook envia mensaje generico pero **no lo persiste**

**Accion**:
1. Agregar try/except individual a `sentiment_analyzer.analyze()` con fallback a heuristic
2. Agregar try/except individual a `memory_manager.build_context()` con fallback a empty history
3. Persistir el correlation_id a traves de todo el pipeline
4. Guardar trace incluso cuando hay errores pre-inference

### P0-C: Log file con rotacion

**Nuevo**: `core/logging_config.py` actualizado para agregar `RotatingFileHandler`
- `LOG_DIR` config (default: `./logs`)
- `LOG_MAX_BYTES`: 10MB por archivo
- `LOG_BACKUP_COUNT`: 5 archivos de backup
- Archivo: `logs/hermes.jsonl` (una linea JSON por entrada)
- Formato: JSON (el mismo que structlog ya produce)

### P0-D: Correlation ID persistido

**Cambios**:
- Pasar `correlation_id` del webhook al `hitl_router.process_inbound_message()`
- Persistir `correlation_id` en `messages` y `agent_decisions`
- Nueva migration:
  ```sql
  ALTER TABLE messages ADD COLUMN correlation_id TEXT;
  ALTER TABLE agent_decisions ADD COLUMN correlation_id TEXT;
  ```

### P0-E: Metrica de fallback

**Nuevo counter**: `hermes_llm_fallback_total` con label `reason`
- Razones: `unavailable`, `error`, `key_invalid`
- Incrementar cuando `generate()` retorna fallback
- Exponer en `/metrics`

### P0-F: Endpoint de diagnostico

**Nuevo**: `GET /api/debug/trace/{phone}`
- Requiere auth (DASHBOARD_TOKEN)
- Retorna ultimos 10 traces de `inference_traces` para ese telefono
- Incluye: prompt enviado, respuesta cruda, si fue fallback o LLM, errores

**Nuevo**: `GET /api/debug/health-detail`
- Retorna: estado del LLM (available/model/key_prefix), ultimo error,
  tasa de fallback vs LLM en ultimas 24h

## Criterio de exito P0

Antes de proceder a P1 (tool calling), debemos poder responder:

1. **"¿Por que el bot respondio 🤔?"** → Mirar `inference_traces` y ver si fue
   `fallback` o `error`, con el error exacto
2. **"¿Que prompt se le envio al LLM?"** → Campo `request_messages` en el trace
3. **"¿Que porcentaje de mensajes son fallback?"** → Metrica
   `hermes_llm_fallback_total / hermes_llm_requests_total`
4. **"¿Cuando fue el ultimo error del LLM?"** → Endpoint `/api/debug/health-detail`
5. **"¿Que paso con el mensaje de Mainer a las 12:22?"** → Buscar por correlation_id
   o phone en traces

## Orden de implementacion P0

| Paso | Archivos | Descripcion | Prioridad |
|------|----------|-------------|-----------|
| **P0-1** | `db/migrations/011_inference_traces.sql` | Tabla `inference_traces` + columnas `correlation_id` | Critica |
| **P0-2** | `db/schema.sql` | Sincronizar schema.sql | Critica |
| **P0-3** | `db/models.py` + `db/database.py` | Model + DB methods para traces | Critica |
| **P0-4** | `core/inference.py` | Retornar trace dict, loggear fallbacks silenciosos | Critica |
| **P0-5** | `core/hitl_router.py` | Persistir trace, propagar correlation_id, logging detallado por paso | Critica |
| **P0-6** | `core/metrics.py` | Counter `hermes_llm_fallback_total` | Alta |
| **P0-7** | `core/logging_config.py` | RotatingFileHandler → `logs/hermes.jsonl` | Alta |
| **P0-8** | `routers/debug.py` | Endpoints `/api/debug/trace/{phone}` y `/api/debug/health-detail` | Media |
| **P0-9** | `main.py` | Registrar router debug | Media |
| **P0-10** | Tests | Tests para trace persistence, fallback metric, debug endpoints | Alta |

## Rollback

P0 es **puramente aditivo** — agrega observabilidad sin cambiar comportamiento existente.
El unico cambio funcional es que `generate()` retorna un 3er elemento en el tuple, pero
el codigo que no lo usa simplemente lo ignora (`text, escalate = generate(...)` funciona
igual en Python). No hay riesgo de rollback.

## Notas de implementacion

### Sobre el 3er retorno de generate()

Python permite unpacking parcial:
```python
# Codigo existente (sigue funcionando):
response_text, llm_escalate = await inference_engine.generate(...)

# Codigo nuevo (usa trace):
response_text, llm_escalate, trace = await inference_engine.generate(...)
```

Esto es backward-compatible porque Python no exige unpackear todos los elementos.

### Sobre el tamanio de request_messages

Un contexto tipico de 16 mensajes + system prompt puede ser ~5-10KB en JSON.
Con 100 conversaciones/dia, la tabla creceria ~500KB-1MB/dia.
Se recomienda agregar un cleanup en el background loop que elimine traces > 30 dias.

### Sobre logging_config.py

El RotatingFileHandler se agrega al lado del StreamHandler existente (stderr).
Ambos handlers reciben los mismos eventos. El formato JSON es el mismo para ambos.
No se modifica el formato ni los processors de structlog.

### Sobre correlation_id

El correlation_id se genera en el webhook y se pasa al hitl_router como parametro.
El hitl_router lo recibe, lo bindea en contextvars, y lo persiste en messages y decisions.
Un solo ID para todo el ciclo de vida del request.

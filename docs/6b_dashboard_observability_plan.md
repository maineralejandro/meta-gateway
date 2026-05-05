# 6b: Dashboard de Observabilidad — Plan de Implementacion

## Objetivo

Agregar un tab "Diagnostico" al dashboard Next.js que consuma los endpoints de debug
existentes (`/api/debug/*`) y aporte valor real al operador: saber si el LLM funciona,
cuantas respuestas son fallback vs. reales, inspeccionar prompts y respuestas crudas,
y actuar rapido cuando algo falla.

## Estandares de diseno

### 1. Data Fetching Activo

- Polling cada 15s en health-detail y traces/recent (no esperar a que el usuario refresque)
- Traces detail se carga on-demand al seleccionar una fila
- Indicador visual de "ultima actualizacion" + boton de refresh manual
- Refresh automatico pausado si el tab no es visible (`document.visibilityState`)

### 2. Tipografia Utilitaria

- Todos los numeros de estado (latency, tokens, scores) en **font-mono**
- Labels en `text-[10px] uppercase tracking-wider text-gray-500`
- Valores en `text-sm font-semibold text-white`
- Colores semanticos: emerald=ok, yellow=warning, red=error, gray=no-data
- Layout tipo "dashboard de control": metrics cards arriba, detalle abajo

### 3. Visor JSON Profesional

- Se usa **react-json-view-lite** (~3KB gzipped, 5K+ GH stars, mantenido)
- Wrapper `JsonViewer.tsx` aplica tema dark con colores de Hermes:
  - Keys: blue-400, Strings: emerald-300, Numbers: cyan-300, Booleans: yellow-300, Null: gray-500
- Collapse/expand nativo de la libreria
- Copy-to-clipboard nativo
- Word-wrap forzado: `style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}`
  para que lineas largas no rompan horizontalmente en laptops 13/14"
- Max display size: si JSON >10KB, mostrar warning + truncar

### 4. Diseno de Alta Densidad

- Aprovechar el viewport completo: sin hero sections, sin whitespace decorativo
- Metrics cards compactas: valor grande + label chica + color semantico
- Tablas con filas de 32px height, fuente 11-12px
- Trace list: tabla scrolleable con columnas fijas (source, latency, time)
- Trace detail: panel lateral **resizable** con drag handle, no pagina nueva
- Todo el tab en un solo viewport sin scroll cuando sea posible

---

## Estructura del tab

```
+---------------------------------------------------------------+
| HERMES  | Conversaciones | Gestion de Agente | Diagnostico   |
+---------------------------------------------------------------+
|                                                                 |
|  [Health Bar] LLM: VERDE | Modelo: gemma-3n | 24h: 142/8/2   |
|                                                                 |
|  +----------+ +----------+ +----------+ +----------+           |
|  | LLM OK   | | Fallback | | Error    | | Avg Lat  |           |
|  | 142      | | 8 (5.3%) | | 2 (1.3%) | | 1.2s     |           |
|  +----------+ +----------+ +----------+ +----------+           |
|                                                                 |
|  [Last Error Banner - si hay]                                   |
|                                                                 |
|  +--- Trace List (izquierda) ---+-- Trace Detail (derecha) ---+|
|  | phone     | source | ms  | t ||◄►| Trace #47               ||
|  | +569..123 | llm    | 800 |.. ||  | ...request_messages      ||
|  | +569..456 | fallback| 2 |.. ||  | ...response_raw           ||
|  | +569..789 | error  | 0  |.. ||  | ...metadata               ||
|  |           |        |    |   ||  |                           ||
|  +------------------------------+------------------------------+|
|                                                                 |
|  [Ultima actualizacion: 14:32:05] [Refresh]                    |
+---------------------------------------------------------------+
```

---

## Componentes nuevos

### 1. `components/observability/HealthBar.tsx`

**Props**: `health: HealthDetail | null`, `lastRefresh: Date | null`, `onRefresh: () => void`

**Que muestra**:
- Badge LLM status: verde (`available=true`) / rojo (`available=false`) / gray (loading)
- Model name (truncado si largo)
- Key prefix (solo los 8 caracteres del endpoint)
- Mini stats 24h: `LLM:142 | FB:8 | ERR:2` con colores
- Timestamp "ultima actualizacion" + boton refresh

**Data source**: `GET /api/debug/health-detail`

**Comportamiento**:
- Se carga al montar el tab
- Auto-refresh cada 15s (pausado si tab no visible)
- Boton manual "Refresh"

**Layout**: una barra horizontal de ~48px height, border-bottom, bg-gray-900

### 2. `components/observability/MetricCards.tsx`

**Props**: `stats: TraceStats | null`

**Que muestra**: 4 cards compactas en fila

| Card | Valor | Label | Color logica |
|------|-------|-------|-------------|
| LLM Responses | `{stats.llm}` | "Respuestas LLM" | emerald si >0, gray si 0 |
| Fallback Rate | `{fallback_pct}%` | "Tasa Fallback (24h)" | emerald <5%, yellow 5-15%, red >15% |
| Error Rate | `{error_pct}%` | "Tasa Error (24h)" | emerald <2%, yellow 2-5%, red >5% |
| Avg Latency | `{stats.avg_llm_latency}ms` | "Latencia Prom. LLM" | emerald <1s, yellow 1-3s, red >3s |

### 3. `components/observability/LastErrorBanner.tsx`

**Props**: `error: LastError | null`

**Que muestra** (solo si `error !== null`):
- Banner rojo de 1 linea: `ERROR: {error_type} — {error_message} @ {phone} {time}`
- Click expande a 2 lineas con correlation_id
- Boton dismiss (X)
- Auto-dismiss despues de 60s

### 4. `components/observability/TraceList.tsx`

**Props**: `traces: TraceSummary[]`, `selectedTraceId: number | null`, `onSelect: (id: number) => void`, `loading: boolean`

**Que muestra**:
- Tabla scrolleable, filas de 32px
- Columnas: `phone` (font-mono, truncated), `source` (badge color), `latency_ms`, `tokens_in/tokens_out`, `created_at`
- Source badges: `llm`=emerald, `fallback`=yellow, `error`=red
- Fila seleccionada con highlight azul
- Filtrable por source (4 botones toggle: All / LLM / Fallback / Error)
- Sort clickable por latency y time

**Data source**: `GET /api/debug/traces/recent?limit=50&source={filter}`

### 5. `components/observability/TraceDetail.tsx`

**Props**: `trace: TraceFull | null`

**Que muestra** (panel derecho resizable, visible solo cuando hay trace seleccionado):

**Seccion Metadata** (compacta, 2 columnas):
- id, correlation_id, agent_id, source, error_type, error_message
- latency_ms, tokens (prompt/completion), created_at

**Seccion Request Messages** (colapsable):
- JsonViewer del campo `request_messages` (parseado de JSON string)
- Default: expandido si <500 chars, colapsado si >500

**Seccion Response Raw** (colapsable):
- JsonViewer del campo `response_raw`
- Si `response_raw` es string simple (no JSON), mostrarlo como texto pre-wrappeado
- Default: expandido

**Seccion Error** (solo si source=error):
- error_type en rojo
- error_message completo

**Layout**: panel derecho con **drag handle resizable**:
- Ancho minimo: 280px
- Ancho default: 50%
- Ancho maximo: 75%
- Handle: barra de 4px en el borde izquierdo, cursor col-resize
- Word-wrap forzado en todo JSON renderizado

### 6. `components/observability/JsonViewer.tsx`

**Props**: `data: any`, `defaultExpanded?: boolean`, `maxSize?: number`

**Wrapper sobre react-json-view-lite** con tema dark de Hermes.

**Configuracion**:
- `collapsed={false}` por defecto
- `style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}` — word-wrap forzado
- Custom theme object mapeando colores Hermes
- Si `JSON.stringify(data).length > maxSize` (default 10KB): mostrar warning + truncar
- Si data es string simple: mostrar como `<pre>` con word-wrap

### 7. `components/observability/ObservabilityTab.tsx`

**Componente orquestador** que compone todos los anteriores.

**State**:
```typescript
interface ObservabilityState {
  health: HealthDetail | null
  stats: TraceStats | null
  lastError: LastError | null
  traces: TraceSummary[]
  selectedTrace: TraceFull | null
  traceFilter: 'all' | 'llm' | 'fallback' | 'error'
  lastRefresh: Date | null
  loading: boolean
  detailWidth: number
}
```

**Data fetching**:
- `fetchHealth()` -> `GET /api/debug/health-detail` (cada 15s)
- `fetchTraces()` -> `GET /api/debug/traces/recent?limit=50&source={filter}` (cada 15s)
- `fetchTraceDetail(id)` -> `GET /api/debug/trace-by-id/{id}` (on select)
- Auto-refresh pausado si `document.hidden === true`
- Boton manual refresh
- Resizable panel state con `detailWidth` persisted en localStorage

---

## Cambios en Backend

### D0: Migration 012 — Indices para traces

```sql
CREATE INDEX IF NOT EXISTS idx_traces_created_at
  ON inference_traces(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_traces_source_created
  ON inference_traces(response_source, created_at DESC);
```

Sin estos indices, `ORDER BY created_at DESC LIMIT 50` hace full table scan.
Con polling cada 15s, esto se vuelve lento con 10K+ traces.

### Nuevo endpoint: `GET /api/debug/traces/recent`

Retorna los ultimos N traces de **todos los telefonos** (no filtrado por phone).

```python
@router.get("/traces/recent")
async def get_recent_traces(
    limit: int = 50,
    source: str | None = None,
    db: Database = Depends(get_db),
) -> Any:
    traces = await db.get_recent_traces(limit=limit, source=source)
    return [
        {
            "id": t.id,
            "phone": t.phone,
            "correlation_id": t.correlation_id,
            "response_source": t.response_source,
            "error_type": t.error_type,
            "token_usage_prompt": t.token_usage_prompt,
            "token_usage_completion": t.token_usage_completion,
            "latency_ms": t.latency_ms,
            "created_at": t.created_at,
        }
        for t in traces
    ]
```

### Nuevo endpoint: `GET /api/debug/trace-by-id/{trace_id}`

Retorna un trace especifico por ID (no por phone).

```python
@router.get("/trace-by-id/{trace_id}")
async def get_trace_by_id(
    trace_id: int,
    db: Database = Depends(get_db),
) -> Any:
    trace = await db.get_trace_by_id(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return { ... full trace fields ... }
```

Path `/trace-by-id/` (no `/trace/{id}`) para evitar conflicto con `/trace/{phone}`.

### Extender `get_trace_stats` con latencia promedio

```sql
SELECT COUNT(*) as total,
       SUM(CASE WHEN response_source = 'llm' THEN 1 ELSE 0 END) as llm_count,
       SUM(CASE WHEN response_source = 'fallback' THEN 1 ELSE 0 END) as fallback_count,
       SUM(CASE WHEN response_source = 'error' THEN 1 ELSE 0 END) as error_count,
       ROUND(AVG(CASE WHEN response_source = 'llm' THEN latency_ms END)) as avg_llm_latency,
       ROUND(AVG(latency_ms)) as avg_latency
FROM inference_traces
WHERE created_at >= datetime('now', ?)
```

Retorna: `{total, llm, fallback, error, avg_llm_latency, avg_latency}`

---

## Interfaces TypeScript

```typescript
interface HealthDetail {
  llm: {
    available: boolean
    model: string
    base_url: string
    key_prefix: string
  }
  trace_stats_24h: TraceStats
  last_error: LastError | null
}

interface TraceStats {
  total: number
  llm: number
  fallback: number
  error: number
  avg_llm_latency: number
  avg_latency: number
}

interface LastError {
  id: number
  phone: string
  correlation_id: string
  error_type: string
  error_message: string
  created_at: string
}

interface TraceSummary {
  id: number
  phone: string
  correlation_id: string
  response_source: 'llm' | 'fallback' | 'error'
  error_type: string | null
  token_usage_prompt: number
  token_usage_completion: number
  latency_ms: number
  created_at: string
}

interface TraceFull {
  id: number
  phone: string
  correlation_id: string
  agent_id: number | null
  request_messages: string
  response_raw: string | null
  response_source: 'llm' | 'fallback' | 'error'
  error_type: string | null
  error_message: string | null
  token_usage_prompt: number
  token_usage_completion: number
  latency_ms: number
  created_at: string
}
```

---

## Integracion en `pages/index.tsx`

El tab actual tiene 2 vistas: `'conversations' | 'agent'`. Se agrega `'observability'`.

```typescript
const [view, setView] = useState<'conversations' | 'agent' | 'observability'>('conversations')
```

En el nav, tercer boton "Diagnostico" con icono `Activity` de lucide-react.

Cuando `view === 'observability'`, renderizar `<ObservabilityTab />`.

El componente `ObservabilityTab` es auto-contenido: maneja su propio state y fetching.
No necesita props del state global de conversaciones.

---

## Orden de implementacion

| Paso | Archivos | Descripcion | Tiempo |
|------|----------|-------------|--------|
| **D0** | `db/migrations/012_trace_indexes.sql` | Indices created_at DESC + source | 5min |
| **D1** | `db/database.py` | `get_recent_traces()`, `get_trace_by_id()`, extender `get_trace_stats()` | 15min |
| **D2** | `routers/debug.py` | Endpoints `/traces/recent`, `/trace-by-id/{id}`, extender health-detail | 20min |
| **D3** | `dashboard/` | Instalar react-json-view-lite, crear `JsonViewer.tsx` wrapper dark | 20min |
| **D4** | `dashboard/components/observability/HealthBar.tsx` | Barra de estado LLM | 20min |
| **D5** | `dashboard/components/observability/MetricCards.tsx` | 4 cards de metricas | 15min |
| **D6** | `dashboard/components/observability/LastErrorBanner.tsx` | Banner de ultimo error | 15min |
| **D7** | `dashboard/components/observability/TraceList.tsx` | Tabla de traces recientes | 30min |
| **D8** | `dashboard/components/observability/TraceDetail.tsx` | Panel resizable + JsonViewer | 40min |
| **D9** | `dashboard/components/observability/ObservabilityTab.tsx` | Orquestador con polling | 40min |
| **D10** | `dashboard/pages/index.tsx` | Agregar tab "Diagnostico" al nav | 10min |
| **D11** | Tests | Backend (nuevos endpoints) + JsonViewer | 45min |
| **D12** | `dashboard/styles/globals.css` | Animaciones y estilos adicionales | 10min |

**Total estimado: ~5h**

---

## Tests

### Backend tests (`tests/test_observability.py` — extendidos)

- `test_get_recent_traces_all` — retorna traces de multiples phones
- `test_get_recent_traces_filtered` — filtro por source
- `test_get_recent_traces_limit` — limita a N
- `test_get_trace_by_id` — retorna trace correcto por ID
- `test_get_trace_by_id_not_found` — 404 para ID inexistente
- `test_trace_stats_avg_latency` — avg_latency se calcula correctamente
- `test_recent_traces_endpoint` — test del endpoint HTTP
- `test_trace_by_id_endpoint` — test del endpoint HTTP

### Dashboard tests (`dashboard/__tests__/JsonViewer.test.tsx`)

- `test_renders_json_object` — verifica que un JSON object se renderiza
- `test_renders_string_fallback` — si data es string simple, renderiza como pre
- `test_large_json_warning` — si JSON > maxSize, muestra warning
- `test_dark_theme_applied` — verifica que los colores del tema se aplican

---

## Riesgos

| Riesgo | Mitigacion |
|--------|-----------|
| react-json-view-lite no soporta word-wrap | Wrapper aplica `whiteSpace: pre-wrap` + `wordBreak: break-word` via style override |
| Polling cada 15s carga el backend | Endpoint con limit=50 max, indices en created_at, pausado si tab no visible |
| request_messages grande (4KB) rompe layout | Word-wrap forzado + panel resizable + JsonViewer collapsed por defecto si >500 chars |
| Indice nuevo en migration 012 | `CREATE INDEX IF NOT EXISTS` — seguro, idempotente |
| TraceDetail panel resizable en mobile | No es target — dashboard es desktop-only por diseno |

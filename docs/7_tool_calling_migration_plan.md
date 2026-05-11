# Plan de Implementacion: Migracion a Tool Calling v2

## Resumen

Migrar el sistema de tags textuales (`[ORDER_ADD:key:qty]`) a **OpenAI Tool Calling** nativo.
El LLM llamara funciones estructuradas con JSON schema, el backend las ejecutara y devolvera
el resultado al LLM para que genere una respuesta informada.

## Beneficios vs sistema actual

1. **Determinismo**: El LLM no puede "alucinar" acciones — si pasa un `item_key` invalido,
   `execute_tool()` retorna un error estructurado con las claves validas, y el LLM puede
   corregir. Hoy, un tag con clave incorrecta se ignora silenciosamente.
2. **Reaccion a errores**: El tool loop permite al LLM ver el resultado de cada accion y
   corregir en tiempo real. Hoy el flujo es one-shot: ejecutar tags y enviar respuesta a ciegas.
3. **System Prompt limpio**: Las tools se auto-documentan via JSON schema. El system prompt
   solo contiene personalidad y reglas del negocio — las instrucciones de tags dejan de
   competir por tokens de contexto.
4. **Flujos transaccionales reales**: El LLM puede ejecutar multiples tools en un turno,
   verificar el estado resultante, y generar una respuesta basada en datos reales del sistema.

## Decisiones tomadas

- **Modelo target**: Mantener el modelo configurado en `.env` (Qwen 3 Next 80B o Llama 3.3 70B).
  **No** se migra a `gemma-3n-e4b-it`. El modelo debe soportar tool calling via API OpenAI-compatible.
- **Migracion incremental**: Dual mode — si hay tools definidas, usa tool loop; si no, usa flujo
  de tags actual. Los tags se eliminan solo en P10 (punto de no retorno).
- **Tool loop**: ejecutar tool -> devolver resultado al LLM -> respuesta final (max 5 iteraciones)
- **Escalacion**: Tool `escalate_to_human` como via principal + string check `ESCALATE_TO_HUMAN`
  como fallback para robustez
- **Costo**: aceptado ~2x por mensaje (priorizar calidad)
- **Idempotencia**: Tabla `tool_executions` con `tool_call_id` como clave de idempotencia
- **Ejecucion secuencial**: Todas las tool calls se ejecutan secuencialmente en la v1.
  El paralelismo (`asyncio.gather`) se deja para optimizacion futura.
- **Estado completo en tool result**: Cada tool de mutacion retorna el estado completo
  post-accion para que el LLM no tenga que inferir.
- **Memoria**: Solo el par user/assistant final se persiste en `turns`. Los mensajes
  intermedios del tool loop (`role: tool`) son efimeros.

---

## Problemas arquitectonicos resueltos

### P1: Idempotencia de Tools

Si `process_turn` falla despues de ejecutar una tool pero antes de guardar el turno,
un reintento duplicaria la accion. Solucion: `tool_call_id` como idempotency key.

```sql
CREATE TABLE IF NOT EXISTS tool_executions (
    tool_call_id TEXT PRIMARY KEY,
    phone TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    result_json TEXT NOT NULL,
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_tool_executions_phone ON tool_executions(phone);
```

Cada `execute_tool()` verifica si ya se ejecuto ese `tool_call_id`:
- Si ya existe: retorna el resultado cacheado (no re-ejecuta).
- Si no existe: ejecuta, guarda, retorna.
- Limpieza: mismo `cleanup_traces(days=30)` se extiende para limpiar `tool_executions`.

### P2: Estado obsoleto en `format_for_context()`

Dentro del mismo tool loop, el contexto inyectado por `format_for_context()` (via `memory.py`)
queda obsoleto tras cada tool de mutacion. Solucion: cada tool result incluye el estado
completo post-accion, para que el LLM nunca tenga que inferir.

Ejemplo para `order_add`:
```python
return {
    "success": True,
    "action": "item_added",
    "item": args["item_key"],
    "qty_added": args["qty"],
    "order_state": {
        "items": [{"key": "completo_normal", "name": "Completo Normal", "qty": 2, "price": 3700}],
        "total": 7400
    },
    "order_summary": "2x Completo Normal ($3,700 c/u) = $7,400 | Total: $7,400"
}
```

Cada capability debe implementar este patron en sus tools de mutacion:

| Capability | Tools con estado completo | Que incluye |
|---|---|---|
| **order** | `order_add`, `order_remove`, `order_clear` | `order_state` + `order_summary` |
| **appointment** | `appointment_add`, `appointment_cancel` | cita creada/cancelada + slots actualizados para esa fecha |
| **membership** | `membership_activate`, `membership_cancel`, `membership_trial` | estado de membresia post-accion + planes si aplican |
| **lead** | `lead_update_field`, `lead_advance_stage` | lead completo post-actualizacion (todos los campos) |

### P3: Parallel Tool Calls

El LLM puede emitir multiples tool calls en una sola respuesta. En la v1, **todas se
ejecutan secuencialmente** en el orden en que aparecen. Esto evita bugs de concurrencia
entre tools de la misma capability (ej: `order_add` + `order_clear` en el mismo turno).

La clasificacion `PARALLEL_SAFE` / `SEQUENTIAL` se define en `BaseCapability` pero no se
usa en la v1. Queda preparada para optimizacion futura:

```python
class BaseCapability(ABC):
    PARALLEL_SAFE_TOOLS: ClassVar[set[str]] = set()
    SEQUENTIAL_TOOLS: ClassVar[set[str]] = set()
```

| Capability | PARALLEL_SAFE | SEQUENTIAL |
|---|---|---|
| **order** | `order_get_menu` | `order_add`, `order_remove`, `order_clear` |
| **appointment** | `appointment_get_available` | `appointment_add`, `appointment_cancel` |
| **membership** | `membership_check`, `membership_get_plans` | `membership_activate`, `membership_cancel`, `membership_trial` |
| **lead** | `lead_get` | `lead_update_field`, `lead_advance_stage` |

### P4: Memoria y tool calls

Los mensajes intermedios del tool loop (`role: assistant` con `tool_calls`, `role: tool`
con resultados) son **efimeros** — solo existen durante la ejecucion del turno.
Solo se persiste en `turns` el par final:

- `user_text`: el mensaje del usuario (sin cambios)
- `assistant_text`: la respuesta final del LLM (despues del tool loop)

Los `tool_calls_executed` se guardan en `inference_traces` como metadata de debugging:
```python
trace["tool_calls_executed"] = json.dumps(result.tools_executed)
trace["tool_loop_iterations"] = result.iterations
```

La memoria episodica (`summarize_session`) y el contexto (`build_context`) solo ven
turnos user/assistant — nunca ven los mensajes internos del tool loop.

### P5: Loop detection

El LLM puede entrar en un ciclo repitiendo la misma tool call con los mismos argumentos.
Solucion: detectar firmas duplicadas e inyectar un error explicito.

```python
seen_signatures: set[str] = set()

for tool_call in message.tool_calls:
    signature = f"{tool_call.function.name}:{tool_call.function.arguments}"
    if signature in seen_signatures:
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps({
                "error": True,
                "message": "Esta accion ya fue intentada y fallo. No reintentes con los mismos argumentos.",
                "instruction": "Informa al usuario del problema. Si no puedes resolverlo, escala a un humano."
            })
        })
        continue
    seen_signatures.add(signature)
    result = await execute_tool(...)
```

Ademas, cada tool result de error es **instructivo** — incluye claves validas, opciones,
o instrucciones claras para que el LLM no reintente a ciegas:

```python
# order_add con item_key invalido
return {
    "success": False,
    "error": "item_key 'completo_gigantes' not found",
    "valid_keys": ["completo_normal", "completo_gigante", ...],
    "instruction": "Usa una de las claves validas listadas arriba."
}
```

---

## Cambios por archivo

### 1. `core/capabilities/base.py` — Nuevo contrato de capability

**Agregar** (sin eliminar lo existente aun — dual mode):

```python
class BaseCapability(ABC):
    # Existente — se mantiene durante dual mode
    name: str = ""
    description: str = ""
    tag_patterns: ClassVar[dict[str, re.Pattern[str]]] = {}
    config_schema: ClassVar[list[dict[str, Any]]] = []

    # Nuevo — v2 tool calling
    PARALLEL_SAFE_TOOLS: ClassVar[set[str]] = set()
    SEQUENTIAL_TOOLS: ClassVar[set[str]] = set()

    @abstractmethod
    async def format_for_context(self, phone: str, config: dict[str, Any]) -> str | None: ...

    @abstractmethod
    async def parse_tags(self, phone: str, text: str, config: dict[str, Any]) -> str: ...

    @abstractmethod
    async def clear(self, phone: str, config: dict[str, Any]) -> None: ...

    @abstractmethod
    def get_prompt_instructions(self, config: dict[str, Any]) -> str: ...

    # Nuevos metodos — con implementacion default para backward compat

    def get_tool_definitions(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Devuelve lista de tool schemas OpenAI para esta capability. Default: vacio."""
        return []

    def get_tool_names(self) -> set[str]:
        """Devuelve los nombres de tools que esta capability maneja. Default: vacio."""
        return set()

    async def execute_tool(self, name: str, args: dict[str, Any], phone: str,
                           tool_call_id: str, config: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una tool por nombre y devuelve resultado serializable. Default: error."""
        return {"success": False, "error": f"Tool '{name}' not implemented"}
```

Los metodos nuevos tienen **implementacion default** para que las capabilities existentes
no rompan al agregar la interfaz. Cada capability los override en su propio paso (P2-P5).

### 2. `core/llm_client.py` — Soporte para tools

**Agregar** parametros `tools` y `tool_choice` en `chat_completion()`:

```python
async def chat_completion(
    self,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 500,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str = "auto",
    log_label: str = "llm_retry",
) -> ChatCompletion:
    client = self.get_client()
    if client is None:
        raise RuntimeError("LLM client not available")

    kwargs: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

    # ... retry loop existente, pasando kwargs ...
```

### 3. `core/inference.py` — Tool execution loop + GenerationResult

**Agregar** dataclass `GenerationResult`:

```python
@dataclass
class GenerationResult:
    text: str
    should_escalate: bool
    escalation_reason: str
    tools_executed: list[dict[str, Any]]
    iterations: int
    prompt_tokens: int
    completion_tokens: int
```

**Reescribir** `generate()` para soportar dual mode:

1. Resolver capabilities y construir `tools` list via `cap.get_tool_definitions()`
2. Si hay tools definidas -> tool loop (nuevo flujo)
3. Si no hay tools -> flujo actual con `get_prompt_instructions()` + `parse_tags()`
4. Retornar `GenerationResult` (no tupla)

**Tool loop** (cuando hay tools):

```
1. Construir messages: system_prompt (sin instrucciones de tags) + history + user_message
2. Agregar tools: schemas de todas las capabilities activas + escalate_to_human
3. Iteracion loop (max TOOL_MAX_ITERATIONS):
   a. Llamar LLM con messages + tools
   b. Si respuesta NO tiene tool_calls:
      - Extraer texto final
      - sanitizar con sanitize_llm_output()
      - Check de ESCALATE_TO_HUMAN como fallback string
      - Retornar GenerationResult
   c. Si respuesta TIENE tool_calls:
      - Agregar mensaje assistant con tool_calls al historial
      - Para cada tool_call:
        - Loop detection (signature duplicada?)
        - Buscar capability que maneja esta tool (via get_tool_names())
        - Ejecutar via capability.execute_tool(name, args, phone, tool_call_id, config)
        - Agregar mensaje role: tool con resultado
        - Si tool == escalate_to_human -> retornar con should_escalate=True
      - Continuar loop (volver a llamar LLM con historial actualizado)
4. Si se agotan iteraciones -> retornar texto de error + no escalar
```

**Eliminar** (solo en modo tool calling):
- Inyeccion de `get_prompt_instructions()` en system prompt
- Check de `escalation_marker` en texto como mecanismo primario (queda como fallback)

**No eliminar** (se mantiene en ambos modos):
- `sanitize_llm_output()` — siempre se aplica al texto final
- `<customer_message>` wrapping — defensa contra prompt injection
- `_normalize_roles()` — normalizacion de mensajes
- Fallback responses — cuando el LLM no esta disponible

### 4. `core/hitl_router.py` — Pipeline simplificado

**Cambiar**:
- `_run_inference()` debe retornar `GenerationResult` en vez de `tuple[str, bool, dict]`
- `_handle_reply()`: eliminar loop de `cap.parse_tags()` y segunda llamada a
  `sanitize_llm_output()` cuando inference retorna por tool calling
- `_handle_escalation()`: usar `escalation_reason` de `GenerationResult` en vez de
  derivarlo solo del sentiment

**Mantener**:
- Sentiment analysis
- Session management
- Memory (build_context + maybe_summarize)
- Per-phone locking
- Event emission
- Meta client messaging

### 5. Cada capability (`order.py`, `appointment.py`, `membership.py`, `lead.py`)

**Agregar**:
- `get_tool_definitions()` — JSON schema de cada tool
- `get_tool_names()` — set de nombres de tools que maneja
- `execute_tool()` — router que despacha por nombre de tool a los metodos existentes
- Cada tool result de mutacion incluye estado completo post-accion

**No eliminar aun** (hasta P10):
- `parse_tags()` implementation
- `get_prompt_instructions()` implementation
- Todos los `*_RE` regex patterns de tags

Los metodos de negocio (`add_item`, `cancel_appointment`, etc.) **no cambian** —
solo se exponen de forma diferente via `execute_tool()`.

### 6. `core/config.py` — Nueva config

- **NO cambiar** `LLM_MODEL` default — mantener `meta/llama-3.3-70b-instruct`
- Agregar `TOOL_MAX_ITERATIONS: int = 5`
- Agregar `TOOL_EXECUTION_TTL: int = 300` (segundos para idempotencia cache)

### 7. `.env.example` — Actualizar

- Agregar `TOOL_MAX_ITERATIONS=5`
- Agregar `TOOL_EXECUTION_TTL=300`
- Mantener `LLM_MODEL=qwen/qwen3-next-80b-a3b-instruct`

### 8. Migracion DB — Nueva tabla

```sql
-- Migration 017: Tool executions idempotency
CREATE TABLE IF NOT EXISTS tool_executions (
    tool_call_id TEXT PRIMARY KEY,
    phone TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    result_json TEXT NOT NULL,
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_tool_executions_phone ON tool_executions(phone);
```

Agregar metodo `cleanup_tool_executions(days=30)` a `db/database.py`.

### 9. Templates — Sin cambios

Los 4 templates en migracion `010_agent_templates.sql` **no contienen tags** — usan
placeholders `{{business_name}}`, `{{products}}`. La migracion `016` ya removio los tags
del system_prompt del agente seed. No se requiere actualizacion de templates.

### 10. Tests

- **Agregar** tests de `get_tool_definitions()` — verifica que los schemas son JSON validos
  y tienen los campos requeridos por OpenAI (`type`, `function.name`, `function.parameters`)
- **Agregar** tests de `execute_tool()` — verifica que cada tool retorna dict con
  `success: True/False` y estado completo cuando aplica
- **Agregar** tests de `get_tool_names()` — verifica que los nombres coinciden con las
  tool definitions
- **Agregar** tests de `InferenceEngine.generate()` con tool loop mockeado:
  - LLM responde con tool_calls -> se ejecutan -> LLM responde con texto
  - LLM responde con tool_calls -> error en tool -> LLM corrige y reintenta
  - Loop detection: misma firma detectada y bloqueada
  - Max iteraciones alcanzadas -> texto de error
  - Escalation via tool `escalate_to_human`
  - Escalation via string fallback `ESCALATE_TO_HUMAN`
  - Dual mode: sin tools -> flujo de tags actual
- **Agregar** tests de idempotencia: mismo `tool_call_id` ejecuta solo una vez
- **Actualizar** `test_conversational.py` — simular respuestas con `tool_calls` en vez de
  tags en texto (los tests de tags se mantienen hasta P10)
- **Agregar** test de `GenerationResult` — verificar que hitl_router lo consume correctamente
- **No eliminar** tests de `parse_tags` hasta P10

### 11. Dashboard — Sin cambios inmediatos

El dashboard ya usa `capability_name` + `config_json`. La API de capabilities no cambia.
Los system prompts de templates no necesitan actualizacion (ver punto 9).

### 12. Escalation tool schema

Tool global (no pertenece a ninguna capability — se agrega en `inference.py`):

```json
{
    "type": "function",
    "function": {
        "name": "escalate_to_human",
        "description": "Escalar la conversacion a un operador humano. Usar cuando el cliente esta molesto, pide cancelar, o cuando no puedes resolver su solicitud.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Razon breve de la escalacion"
                }
            },
            "required": ["reason"]
        }
    }
}
```

---

## Tool schemas detallados

### order

```json
[
    {
        "type": "function",
        "function": {
            "name": "order_add",
            "description": "Agregar un item al pedido del cliente. Retorna el estado completo del pedido despues de agregar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string", "description": "Clave del item del menu (ej: completo_normal, coca_lata)"},
                    "qty": {"type": "integer", "description": "Cantidad a agregar", "minimum": 1}
                },
                "required": ["item_key", "qty"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "order_remove",
            "description": "Quitar un item del pedido del cliente. Si qty se omite, quita todo el item. Retorna el estado completo del pedido.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string", "description": "Clave del item del menu"},
                    "qty": {"type": "integer", "description": "Cantidad a quitar. Si se omite, quita todo."}
                },
                "required": ["item_key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "order_clear",
            "description": "Limpiar todo el pedido del cliente. Retorna confirmacion.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "order_get_menu",
            "description": "Obtener el menu disponible con nombres, claves y precios. Usar cuando el cliente pregunta por productos o precios.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]
```

### appointment

```json
[
    {
        "type": "function",
        "function": {
            "name": "appointment_add",
            "description": "Agendar una cita para el cliente. Retorna la cita creada y los slots actualizados para esa fecha.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "format": "date", "description": "Fecha YYYY-MM-DD"},
                    "time": {"type": "string", "description": "Hora HH:MM"},
                    "service_key": {"type": "string", "description": "Clave del servicio"}
                },
                "required": ["date", "time", "service_key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "appointment_cancel",
            "description": "Cancelar una cita del cliente. Retorna confirmacion y slots actualizados.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "format": "date", "description": "Fecha YYYY-MM-DD"},
                    "time": {"type": "string", "description": "Hora HH:MM"}
                },
                "required": ["date", "time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "appointment_get_available",
            "description": "Consultar horas disponibles para una fecha. Usar antes de agendar para mostrar opciones al cliente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "format": "date", "description": "Fecha YYYY-MM-DD"}
                },
                "required": ["date"]
            }
        }
    }
]
```

### membership

```json
[
    {
        "type": "function",
        "function": {
            "name": "membership_activate",
            "description": "Activar un plan de membresia para el cliente. Retorna el estado completo de la membresia.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_key": {"type": "string", "description": "Clave del plan (ej: basico, premium, anual)"}
                },
                "required": ["plan_key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "membership_cancel",
            "description": "Cancelar la membresia activa del cliente. Retorna confirmacion.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "membership_trial",
            "description": "Activar un trial gratuito para el cliente. Solo disponible si la config lo permite. Retorna el estado de la membresia.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_key": {"type": "string", "description": "Clave del plan para el trial"}
                },
                "required": ["plan_key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "membership_check",
            "description": "Consultar el estado de la membresia del cliente. Retorna estado actual o indica que no tiene membresia.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "membership_get_plans",
            "description": "Listar los planes de membresia disponibles con precios y caracteristicas.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]
```

### lead

```json
[
    {
        "type": "function",
        "function": {
            "name": "lead_update_field",
            "description": "Actualizar un campo de informacion del prospecto (nombre, email, presupuesto, zona, etc.). Retorna el lead completo con todos los campos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "description": "Nombre del campo (ej: nombre, email, presupuesto, zona)"},
                    "value": {"type": "string", "description": "Valor del campo"}
                },
                "required": ["field", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lead_advance_stage",
            "description": "Avanzar el prospecto a la siguiente etapa del pipeline de ventas. Retorna el lead completo con la nueva etapa.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stage": {"type": "string", "description": "Etapa destino (ej: interesado, calificado, visita, propuesta, cerrado)"}
                },
                "required": ["stage"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lead_get",
            "description": "Obtener la informacion actual del prospecto. Usar para ver que datos faltan antes de actualizar.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]
```

---

## Flujo de mensaje con Tool Calling

```
WhatsApp User
    |
    v
Meta Cloud API --webhook--> webhook.py
    |
    v
hitl_router.process_inbound_message(phone, text)
    |
    +-- sentiment_analyzer.analyze(text)
    +-- capability_registry.resolve(agent_id)
    |   -> [OrderCapability, AppointmentCapability, ...]
    +-- memory.build_context(phone, capabilities) -> history
    |   (format_for_context() inyecta estado actual en historial)
    |
    v
inference_engine.generate(text, history, agent_id, capabilities)
    |
    +-- Construir tools: cap.get_tool_definitions() de cada capability
    |                     + escalate_to_human schema
    +-- Si hay tools definidas:
    |   |
    |   +-- Construir messages: system_prompt + history + user_message
    |   +-- TOOL LOOP (max 5 iteraciones):
    |   |   |
    |   |   +-- LLM call: chat.completions.create(messages, tools=tool_schemas)
    |   |   |
    |   |   +-- Si respuesta tiene tool_calls:
    |   |   |   +-- Agregar assistant message con tool_calls
    |   |   |   +-- Para cada tool_call (secuencial):
    |   |   |   |   +-- Loop detection (signature duplicada?)
    |   |   |   |   +-- Idempotencia check (tool_call_id ya ejecutado?)
    |   |   |   |   +-- capability.execute_tool(name, args, phone, tool_call_id, config)
    |   |   |   |   +-- Agregar role: tool message con resultado
    |   |   |   |   +-- Si tool == escalate_to_human -> RETORNAR should_escalate=True
    |   |   |   +-- Continuar loop
    |   |   |
    |   |   +-- Si respuesta es texto final (sin tool_calls):
    |   |       +-- sanitize_llm_output(text)
    |   |       +-- Check fallback ESCALATE_TO_HUMAN en texto
    |   |       +-- RETORNAR GenerationResult
    |   |
    |   +-- Si max iteraciones: RETORNAR texto de error
    |
    +-- Si NO hay tools definidas (dual mode / legacy):
        +-- Flujo actual: get_prompt_instructions() + system prompt
        +-- LLM call unico
        +-- RETORNAR GenerationResult (compatible)
    |
    v
hitl_router:
    +-- Si should_escalate -> _handle_escalation()
    +-- Si no -> _handle_reply()
        +-- enviar response_text via meta_client
        +-- guardar turno en DB (solo par user/assistant final)
```

---

## Orden de implementacion

### Semana 1 — Fundación

| Paso | Archivos | Descripcion | Verificacion | Riesgo |
|------|----------|-------------|-------------|--------|
| **P1** | `core/capabilities/base.py` | Nuevo contrato: `get_tool_definitions`, `get_tool_names`, `execute_tool`, `PARALLEL_SAFE_TOOLS`, `SEQUENTIAL_TOOLS` con implementacion default | Tests unitarios: instanciar subclass con defaults, verificar que no rompe | Bajo |
| **P6** | `core/llm_client.py` | Agregar `tools` + `tool_choice` params a `chat_completion()`. Pasar solo si `tools is not None` | Test: llamar chat_completion con tools=None (comportamiento actual) y con tools=[] (no rompe) | Bajo |

### Semana 2 — Capabilities

| Paso | Archivos | Descripcion | Verificacion | Riesgo |
|------|----------|-------------|-------------|--------|
| **P2** | `core/capabilities/order.py` | `get_tool_definitions` + `get_tool_names` + `execute_tool` (4 tools). Tool results con estado completo | Tests: cada tool retorna dict con `success`, `order_state`, `order_summary`. Clave invalida retorna `valid_keys`. | Bajo |
| **P3** | `core/capabilities/appointment.py` | `get_tool_definitions` + `get_tool_names` + `execute_tool` (3 tools). Slots actualizados en result | Tests: cada tool retorna dict con `success`. appointment_add retorna slots actualizados. | Bajo |
| **P4** | `core/capabilities/membership.py` | `get_tool_definitions` + `get_tool_names` + `execute_tool` (5 tools, incluye `membership_trial`). Estado completo en result | Tests: cada tool retorna dict con `success`. membership_trial respeta config `allow_free_trial`. | Bajo |
| **P5** | `core/capabilities/lead.py` | `get_tool_definitions` + `get_tool_names` + `execute_tool` (3 tools). Lead completo en result | Tests: cada tool retorna dict con `success` + lead completo con todos los campos. | Bajo |

### Semana 3 — El nucleo

| Paso | Archivos | Descripcion | Verificacion | Riesgo |
|------|----------|-------------|-------------|--------|
| **P7** | `core/inference.py` | Tool loop completo: `GenerationResult`, dual mode, loop detection, escalation via tool + string fallback, timeout por iteracion | **GATE OBLIGATORIA** (ver abajo) | **Alto** |

#### GATE P7 — Pruebas manuales obligatorias

Antes de continuar a P8, ejecutar las siguientes pruebas manuales con el modelo configurado
en `.env` (Qwen 3 Next 80B o Llama 3.3 70B via NVIDIA NIM):

| # | Prueba | Criterio de exito | Falla si |
|---|--------|-------------------|----------|
| G1 | "Hola, quiero 2 completos normales" | LLM llama `order_add("completo_normal", 2)` -> genera respuesta con total correcto | LLM no usa tool, o usa clave incorrecta sin corregir |
| G2 | "Agrega una coca y quita el completo" | LLM llama `order_remove` + `order_add` en una iteracion, respuesta refleja estado correcto | LLM no llama tools, o estado final incorrecto |
| G3 | "Quiero un completo gigantes" (clave invalida) | LLM llama `order_add("completo_gigantes", 1)` -> recibe error con `valid_keys` -> corrige a `completo_gigante` | LLM reintenta misma clave 3+ veces (loop detection falla) |
| G4 | "Quiero cancelar todo, estoy molesto" | LLM llama `escalate_to_human` tool con reason | LLM no escala, o responde normalmente |
| G5 | "Queda algo a las 3 del viernes?" (appointment) | LLM llama `appointment_get_available` -> muestra slots al cliente | LLM inventa horarios sin consultar tool |
| G6 | " limpia mi pedido" | LLM llama `order_clear()` -> respuesta confirma pedido vacio | LLM no llama tool |
| G7 | Dual mode: agente sin tools definidas | Flujo de tags actual funciona sin cambios | Cualquier regresion vs comportamiento actual |
| G8 | 5+ tools en una iteracion | Tool loop procesa todas, LLM genera respuesta coherente | Loop excede max iteraciones |

**Si el modelo falla >2 de estas pruebas**: evaluar cambio de modelo ANTES de continuar.
P7 se puede revertir al dual mode (flujo tags) sin perder P1-P6.

### Semana 4 — Integracion, idempotencia y limpieza

| Paso | Archivos | Descripcion | Verificacion | Riesgo |
|------|----------|-------------|-------------|--------|
| **P8** | `core/hitl_router.py` | Eliminar `parse_tags` loop, actualizar a `GenerationResult`, eliminar segunda `sanitize_llm_output` | Tests de integracion: flujo completo end-to-end con tool calling | Medio |
| **P9** | Tests | Agregar todos los tests nuevos (ver seccion 10). Actualizar `test_conversational.py` | `python3 -m pytest tests/ -v` pasa 100% | Medio |
| **P0b** | `db/migrations/017_tool_executions.sql` + `db/database.py` | Tabla `tool_executions` + idempotencia por `tool_call_id` + cleanup | Test: ejecutar misma tool_call_id dos veces, segunda retorna cache sin re-ejecutar | Bajo |
| **P10** | TODO el codebase | **Punto de no retorno** — eliminar `parse_tags`, `get_prompt_instructions`, `tag_patterns`, todos los `*_RE` regex, segunda `sanitize_llm_output` en hitl_router | `python3 -m pytest tests/ -v` pasa 100%. `grep -r "parse_tags\|ORDER_TAG_RE\|APPOINTMENT_ADD_RE" core/` retorna 0 resultados | Bajo |
| **P11** | `core/config.py` + `.env.example` | Agregar `TOOL_MAX_ITERATIONS`, `TOOL_EXECUTION_TTL`. Actualizar `.env.example` | `python3 -m mypy core/config.py` pasa. `.env.example` tiene nuevas vars | Bajo |

---

## Checklist de verificacion completa

Este checklist debe pasar al 100% antes de considerar la migracion completa.

### Funcionalidad core

- [ ] `order_add(item_key, qty)` ejecuta correctamente y retorna estado completo
- [ ] `order_add` con clave invalida retorna `valid_keys` y `instruction`
- [ ] `order_remove(item_key, qty?)` ejecuta correctamente y retorna estado completo
- [ ] `order_clear()` limpia el pedido y retorna confirmacion
- [ ] `order_get_menu()` retorna el menu con claves, nombres y precios
- [ ] `appointment_add(date, time, service_key)` crea cita y retorna slots actualizados
- [ ] `appointment_add` con slot ocupado retorna error claro
- [ ] `appointment_cancel(date, time)` cancela y retorna slots actualizados
- [ ] `appointment_get_available(date)` retorna slots disponibles
- [ ] `membership_activate(plan_key)` activa plan y retorna estado completo
- [ ] `membership_activate` con plan invalido retorna `valid_plans`
- [ ] `membership_cancel()` cancela membresia activa
- [ ] `membership_trial(plan_key)` activa trial solo si `allow_free_trial=True`
- [ ] `membership_check()` retorna estado actual
- [ ] `membership_get_plans()` lista planes disponibles
- [ ] `lead_update_field(field, value)` actualiza campo y retorna lead completo
- [ ] `lead_advance_stage(stage)` avanza etapa y retorna lead completo
- [ ] `lead_advance_stage` con etapa invalida retorna `valid_stages`
- [ ] `lead_get()` retorna lead actual con todos los campos

### Tool loop

- [ ] LLM recibe tools via API y las usa correctamente (G1-G8)
- [ ] Tool loop funciona con 1 iteracion (tool call -> respuesta final)
- [ ] Tool loop funciona con 2+ iteraciones (tool call -> error -> tool call -> respuesta)
- [ ] Max iteraciones (5) detiene el loop y retorna texto de error
- [ ] Loop detection bloquea firmas duplicadas e inyecta error instructivo
- [ ] Escalation via tool `escalate_to_human` retorna `should_escalate=True`
- [ ] Escalation via string `ESCALATE_TO_HUMAN` funciona como fallback
- [ ] Tool result de error es instructivo (incluye `valid_keys`, `instruction`, etc.)

### Idempotencia

- [ ] Misma `tool_call_id` ejecuta solo una vez (segunda retorna cache)
- [ ] `tool_executions` se limpia automaticamente con `cleanup_tool_executions(30)`
- [ ] Timeout de TTL (300s) expira y permite re-ejecucion

### Dual mode

- [ ] Si capabilities no definen tools (`get_tool_definitions()` retorna `[]`), flujo de tags funciona sin cambios
- [ ] Si capabilities definen tools, flujo de tool calling se usa automaticamente
- [ ] Ambos modos retornan `GenerationResult` compatible con `hitl_router`

### Memoria y persistencia

- [ ] Solo el par user/assistant final se guarda en `turns`
- [ ] Mensajes intermedios del tool loop (`role: tool`) NO se persisten en `turns`
- [ ] `tools_executed` se guarda en `inference_traces` como metadata
- [ ] `tool_loop_iterations` se guarda en `inference_traces`
- [ ] `format_for_context()` sigue inyectando estado en `memory.build_context()` (sin cambios)
- [ ] `summarize_session()` no ve tool messages intermedios
- [ ] `maybe_summarize()` funciona igual que antes

### Regresion

- [ ] Sentiment analysis funciona igual
- [ ] Escalation por sentiment (score < 0.3) funciona igual
- [ ] Escalation por keyword funciona igual
- [ ] Escalation por confianza baja funciona igual
- [ ] Session timeout (4h) limpia estado de capabilities
- [ ] Webhook idempotencia (meta_message_id UNIQUE) funciona igual
- [ ] Rate limiting inbound funciona igual
- [ ] Debouncing (5s silence window) funciona igual
- [ ] Per-phone locking funciona igual
- [ ] `<customer_message>` wrapping funciona igual
- [ ] `sanitize_llm_output()` se aplica al texto final

### Limpieza (P10)

- [ ] `parse_tags` eliminado de todas las capabilities
- [ ] `get_prompt_instructions` eliminado de todas las capabilities
- [ ] `tag_patterns` eliminado de `BaseCapability`
- [ ] Todos los `*_RE` regex eliminados de cada capability
- [ ] Segunda llamada a `sanitize_llm_output` en `hitl_router.py` eliminada
- [ ] Tests de `parse_tags` eliminados
- [ ] `grep -r "parse_tags\|ORDER_TAG_RE\|APPOINTMENT_ADD_RE\|MEMBERSHIP_CHECK_RE\|LEAD_UPDATE_RE" core/` retorna 0
- [ ] `grep -r "get_prompt_instructions" core/` retorna 0

### Tests

- [ ] `python3 -m pytest tests/ -v` pasa 100% despues de cada paso
- [ ] `python3 -m ruff check .` pasa sin errores
- [ ] `python3 -m mypy core/ db/ routers/ main.py` pasa sin errores
- [ ] Test coverage de `execute_tool()` >= 90% por capability
- [ ] Test coverage de tool loop en `inference.py` >= 80%

---

## Puntos de rollback

| Punto | Que se revierte | Como |
|-------|----------------|------|
| **P7** | Tool loop en inference.py | Revertir a flujo de tags. P1-P6 son additive (no rompen nada). |
| **P8** | hitl_router sin parse_tags | Revertir commit. Los metodos `parse_tags` aun existen en capabilities hasta P10. |
| **P10** | Eliminacion de tags | **Punto de no retorno**. Crear branch `tags-backup` antes de ejecutar P10. |

---

## Riesgos identificados

| Riesgo | Probabilidad | Impacto | Mitigacion |
|--------|-------------|---------|------------|
| Modelo no sigue tool schemas | Media | Alto — tool loop no funciona | GATE P7 con pruebas manuales. Si falla, evaluar cambio de modelo antes de continuar. Dual mode como fallback. |
| Tool loop infinito | Baja | Medio — consumo de tokens | Max 5 iteraciones + loop detection por signature + tool results instructivos |
| Tool args invalidos del LLM | Media | Bajo — tool retorna error | `execute_tool` hace validacion defensiva, retorna error con datos correctivos (`valid_keys`, `instruction`) |
| Costo ~2x por mensaje | Alta | Bajo — aceptado por diseno | Monitorear tokens via `inference_traces`. Si excede 3x, optimizar prompts o reducir `max_tokens`. |
| DB state inconsistente si tool falla mitad del loop | Baja | Medio — pedido parcial | Cada tool es atomica (una DB write por tool). Idempotencia via `tool_call_id` previene duplicacion. |
| Regresion en flujo de tags | Baja | Alto — bot deja de funcionar | Dual mode: si no hay tools, usa flujo tags. Tests de regresion ejecutan ambos modos. |
| `GenerationResult` rompe callers | Media | Medio — hitl_router espera tupla | P8 actualiza hitl_router explicitamente. Tests de integracion verifican. |
| Tool result muy grande consume tokens | Baja | Bajo — ~100-200 tokens por result | `order_summary` es texto corto. `order_state` es JSON compacto. Monitorear. |

---

## Cambios vs plan v1

| Aspecto | Plan v1 | Plan v2 (este documento) | Razon |
|---------|---------|-------------------------|-------|
| Modelo target | `google/gemma-3n-e4b-it` | Modelo actual en `.env` (Qwen/Llama) | Gemma 3N es demasiado pequeno para tool calling confiable. El proyecto ya evoluciono a modelos mas capaces. |
| Tags | Eliminar sin backward compat | Dual mode hasta P10 | Permite rollback seguro y migracion incremental. |
| Escalation | Sin decision | Tool `escalate_to_human` + string fallback | Dos vias de escalacion para robustez. Tool es estructurado, string es safety net. |
| Idempotencia | No mencionada | Tabla `tool_executions` + `tool_call_id` | Previene duplicacion silenciosa en reintentos. |
| Estado en tool result | No mencionado | Cada tool de mutacion retorna estado completo | El LLM nunca infiere — ve el estado real post-accion. |
| Parallel tool calls | No mencionado | Definido pero no usado en v1 (secuencial) | Evita bugs de concurrencia. Preparado para optimizar despues. |
| Memoria y tool loop | No mencionado | Solo par user/assistant final se persiste | Mensajes intermedios son efimeros. Evita contaminar contexto futuro. |
| Loop detection | No mencionado | Firma `name:arguments` + error instructivo | Previene ciclos del LLM repitiendo la misma tool fallida. |
| Templates | "Actualizar system prompts" | Sin cambios | Migracion 016 ya limpio tags. Templates no contienen tags. |
| `order_get_menu` | Incluida como tool | Incluida como tool de solo lectura | Consultiva: el LLM pide el menu solo cuando lo necesita. |
| Verificacion | Sin gate | GATE P7 con 8 pruebas manuales obligatorias | Verifica que el modelo soporta tool calling antes de eliminar tags. |
| Checklist | No existe | 50+ items de verificacion | Asegura 100% de cumplimiento del plan. |

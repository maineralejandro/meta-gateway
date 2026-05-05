# Plan de Implementacion: Migracion a Tool Calling

## Resumen

Migrar el sistema de tags textuales (`[ORDER_ADD:key:qty]`) a **OpenAI Tool Calling** nativo.
El LLM llamara funciones estructuradas con JSON schema, el backend las ejecutara y devolvera
el resultado al LLM para que genere una respuesta informada.

## Decisiones tomadas

- **Modelo target**: `google/gemma-3n-e4b-it` via NVIDIA NIM
- **Tags**: eliminar completamente, sin backward compat
- **Tool loop**: ejecutar tool -> devolver resultado al LLM -> respuesta final (max 5 iteraciones)
- **Costo**: aceptado ~2x por mensaje (priorizar calidad)

---

## Cambios por archivo

### 1. `core/capabilities/base.py` — Nuevo contrato de capability

**Eliminar**:
- `tag_patterns` ClassVar
- `parse_tags()` abstract method
- `get_prompt_instructions()` abstract method

**Agregar**:
- `get_tool_definitions(config) -> list[dict]` — devuelve lista de tool schemas OpenAI para esta capability
- `execute_tool(name, args, phone, config) -> dict` — ejecuta una tool y devuelve resultado serializable
- `format_for_context()` se mantiene igual (inyectar estado en el contexto)

| Capability | Tools que expone |
|---|---|
| **order** | `order_add(item_key, qty)`, `order_remove(item_key, qty)`, `order_clear()`, `order_get_menu()` |
| **appointment** | `appointment_add(date, time, service_key)`, `appointment_cancel(date, time)`, `appointment_get_available(date)` |
| **membership** | `membership_activate(plan_key)`, `membership_cancel()`, `membership_trial(plan_key)`, `membership_check()`, `membership_get_plans()` |
| **lead** | `lead_update_field(field, value)`, `lead_advance_stage(stage)`, `lead_get()` |

### 2. `core/llm_client.py` — Soporte para tools

**Agregar** parametro `tools` y `tool_choice` en `chat_completion()`:

```python
async def chat_completion(
    self, messages, *, max_tokens=500, tools=None, tool_choice="auto"
) -> ChatCompletion:
```

### 3. `core/inference.py` — Tool execution loop

**Reescribir** `generate()` para:

1. Construir messages con system prompt (sin instrucciones de tags) + `tools` parameter
2. Llamar al LLM
3. Si respuesta tiene `tool_calls` -> ejecutar cada tool via `capability.execute_tool()`
   -> agregar `tool` messages -> llamar al LLM de nuevo
4. Repetir hasta max 5 iteraciones o hasta que el LLM responda sin tool_calls
5. Retornar texto final + flag de escalation

**Eliminar**:
- Inyeccion de `get_prompt_instructions()` en system prompt
- Check de `escalation_marker` en texto (migrar a tool `escalate_to_human` o mantener como string check)

### 4. `core/hitl_router.py` — Pipeline simplificado

**Eliminar**:
- Bucle de `cap.parse_tags()` sobre cada capability
- `sanitize_llm_output()` post-tags (el LLM ya no emite tags)

**Mantener**:
- Todo lo demas (sentiment, escalation, session, memory, meta_client)

### 5. Cada capability (`order.py`, `appointment.py`, `membership.py`, `lead.py`)

**Eliminar**:
- `parse_tags()` implementation
- `get_prompt_instructions()` implementation
- Todos los `*_RE` regex patterns de tags

**Agregar**:
- `get_tool_definitions()` — JSON schema de cada tool
- `execute_tool()` — router que despacha por nombre de tool a los metodos existentes
  (`add_item`, `cancel_appointment`, etc.)

Los metodos de negocio (`add_item`, `cancel_appointment`, etc.) **no cambian** —
solo se exponen de forma diferente.

### 6. `core/config.py` — Nueva config

- `LLM_MODEL` default cambia a `"google/gemma-3n-e4b-it"`
- Agregar `TOOL_MAX_ITERATIONS: int = 5`

### 7. `.env.example` — Actualizar modelo default

### 8. Migracion DB — No necesaria

No hay cambios de schema. Las capabilities existentes en `agent_capabilities` siguen
funcionando con `capability_name` y `config_json`. Solo cambia como el LLM las invoca.

### 9. Templates — Actualizar system prompts

Los 4 templates en migration `010_agent_templates.sql` tienen `system_prompt_template`
que mencionan tags. Reemplazar con instrucciones genericas (el LLM ya no necesita saber
de tags, las tools se auto-documentan).

### 10. Tests

- **Eliminar** tests de `parse_tags` (los regex-matching tests en cada capability)
- **Agregar** tests de `get_tool_definitions()` — verifica que los schemas son JSON validos
- **Agregar** tests de `execute_tool()` — verifica que cada tool retorna dict correcto
- **Agregar** tests de `InferenceEngine.generate()` con tool loop mockeado
- **Actualizar** `test_conversational.py` — simular respuestas con `tool_calls` en vez de
  tags en texto
- **Actualizar** `test_capabilities_api.py` — `config_schema` se mantiene, pero
  `description` puede cambiar

### 11. Dashboard — Sin cambios inmediatos

El dashboard ya usa `capability_name` + `config_json`. La API de capabilities no cambia.
Solo los system prompts de templates se actualizan.

---

## Orden de implementacion

| Paso | Archivos | Descripcion | Riesgo |
|------|----------|-------------|--------|
| **P1** | `base.py` | Nuevo contrato: `get_tool_definitions` + `execute_tool` (sin eliminar `parse_tags` aun) | Bajo |
| **P2** | `order.py` | Implementar `get_tool_definitions` + `execute_tool` para order | Bajo |
| **P3** | `appointment.py` | Idem para appointment | Bajo |
| **P4** | `membership.py` | Idem para membership | Bajo |
| **P5** | `lead.py` | Idem para lead | Bajo |
| **P6** | `llm_client.py` | Agregar `tools` param a `chat_completion` | Bajo |
| **P7** | `inference.py` | Implementar tool execution loop (dual mode: si hay tools usa loop, si no usa flujo actual) | Medio |
| **P8** | `hitl_router.py` | Eliminar `parse_tags` loop, delegar a inference | Medio |
| **P9** | Tests | Actualizar todos los tests | Medio |
| **P10** | Limpiar | Eliminar `parse_tags`, `get_prompt_instructions`, tag regexes de todo el codebase | Bajo |
| **P11** | `config.py` + templates | Cambiar modelo default, actualizar system prompts | Bajo |

## Puntos de rollback

- **P7**: Si tool calling no funciona bien con Gemma 3N E4B, podemos revertir inference.py
  y volver a tags
- **P10**: Punto de no retorno — eliminamos tags para siempre
- Recomendacion: mantener un branch `tags-backup` antes de P10

## Riesgos identificados

| Riesgo | Mitigacion |
|--------|-----------|
| Gemma 3N E4B no sigue bien tool schemas | Probar primero con tool calls simples (order_add). Si falla >30%, evaluar Llama 3.3 70B |
| Tool loop infinito | Max 5 iteraciones hard limit + timeout global 30s |
| Tool args invalidos del LLM | `execute_tool` hace validation defensiva, retorna error dict |
| Costo 2x | Aceptado por decision del usuario |
| DB state inconsistente si tool falla mitad del loop | Cada tool es atomica (una DB write por tool) |

---

## Tool schemas detallados

### order

```json
[
  {
    "type": "function",
    "function": {
      "name": "order_add",
      "description": "Agregar un item al pedido del cliente",
      "parameters": {
        "type": "object",
        "properties": {
          "item_key": {"type": "string", "description": "Clave del item del menu"},
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
      "description": "Quitar un item del pedido del cliente",
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
      "description": "Limpiar todo el pedido del cliente",
      "parameters": {"type": "object", "properties": {}}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "order_get_menu",
      "description": "Obtener el menu disponible con precios",
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
      "description": "Agendar una cita para el cliente",
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
      "description": "Cancelar una cita del cliente",
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
      "description": "Consultar horas disponibles para una fecha",
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
      "description": "Activar un plan de membresia para el cliente",
      "parameters": {
        "type": "object",
        "properties": {
          "plan_key": {"type": "string", "description": "Clave del plan"}
        },
        "required": ["plan_key"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "membership_cancel",
      "description": "Cancelar la membresia del cliente",
      "parameters": {"type": "object", "properties": {}}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "membership_trial",
      "description": "Activar un trial gratuito para el cliente",
      "parameters": {
        "type": "object",
        "properties": {
          "plan_key": {"type": "string", "description": "Clave del plan"}
        },
        "required": ["plan_key"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "membership_check",
      "description": "Consultar el estado de la membresia del cliente",
      "parameters": {"type": "object", "properties": {}}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "membership_get_plans",
      "description": "Listar los planes de membresia disponibles",
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
      "description": "Actualizar un campo de informacion del prospecto",
      "parameters": {
        "type": "object",
        "properties": {
          "field": {"type": "string", "description": "Nombre del campo"},
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
      "description": "Avanzar el prospecto a la siguiente etapa del pipeline",
      "parameters": {
        "type": "object",
        "properties": {
          "stage": {"type": "string", "description": "Etapa destino"}
        },
        "required": ["stage"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "lead_get",
      "description": "Obtener la informacion actual del prospecto",
      "parameters": {"type": "object", "properties": {}}
    }
  }
]
```

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
    |      -> [OrderCapability, AppointmentCapability, ...]
    +-- capability.get_tool_definitions(config)  -> tool_schemas
    +-- memory.build_context(phone, capabilities)  -> history
    |
    v
inference_engine.generate(text, history, agent_id, capabilities)
    |
    +-- Construir messages: system_prompt + history + user_message
    +-- Agregar tools: tool_schemas de todas las capabilities activas
    |
    +-- LLM call #1: chat.completions.create(messages, tools=tool_schemas)
    |
    +-- Si response.choices[0].message.tool_calls:
    |      for each tool_call:
    |          result = capability.execute_tool(name, args, phone, config)
    |          messages.append(tool_message with result)
    |      LLM call #2: chat.completions.create(messages, tools=tool_schemas)
    |      ... (repeat up to 5 times)
    |
    +-- Si response.choices[0].message.content:
           return text, should_escalate
    |
    v
hitl_router: enviar response_text via meta_client
```

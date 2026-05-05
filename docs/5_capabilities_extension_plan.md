# Plan: Sistema de Capabilities — De Food Truck a Plataforma Multi-Negocio

## Problema

Hermes tiene un solo "state machine" hardcodeado: `OrderState` (carrito de compras con items, cantidades, precios). Toda interacción no-escalada pasa por `parse_tags()` que solo entiende `[ORDER_ADD]`, `[ORDER_REMOVE]`, `[ORDER_CLEAR]`.

Si eres un dentista, no tienes items — tienes citas. Si eres un gym, tienes membresías. Si eres una inmobiliaria, tienes leads. El sistema no puede modelar nada de eso.

## Solución

Cada agente declara qué **capability** (módulo de estado) necesita. El HITL router y el memory manager consultan esa configuración para saber qué state procesar y qué contexto inyectar.

---

## Modelo de Datos: `agent_capabilities`

Tabla relacional con JSON embebido para config específica:

```sql
CREATE TABLE IF NOT EXISTS agent_capabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL,
    capability_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    UNIQUE(agent_id, capability_name)
);

CREATE INDEX idx_agent_capabilities_agent ON agent_capabilities(agent_id);
CREATE INDEX idx_agent_capabilities_active ON agent_capabilities(agent_id, is_active);
```

### Significado de cada campo

| Campo | Propósito |
|-------|-----------|
| `capability_name` | Nombre registrado en `CapabilityRegistry`: `"order"`, `"appointment"`, `"membership"`, `"lead"` |
| `is_active` | Permite desactivar una capability sin eliminarla (pausar citas temporalmente, etc.) |
| `config_json` | Configuración específica por capability. Cada capability define su propio schema sin ALTER TABLE |

### Ejemplos de `config_json` por capability

**order**: `{"menu_source": "db", "currency": "CLP"}`
**appointment**: `{"business_hours": {"mon-fri": "09:00-18:00", "sat": "10:00-14:00"}, "slot_duration_minutes": 30, "services": ["limpieza", "control", "blanqueamiento"]}`
**membership**: `{"plans_source": "db", "allow_free_trial": true, "trial_days": 7}`
**lead**: `{"stages": ["interesado", "calificado", "visita", "propuesta", "cerrado"], "fields": ["presupuesto", "zona", "tipo_propiedad"]}`

### Por qué relacional + JSON (no solo JSON en agents)

- **Relacional**: JOINs limpios para saber qué agentes tienen qué módulos activos (vital para analíticas o facturación del SaaS)
- **JSON aislado (config_json)**: Flexibilidad para guardar config específica sin alterar el schema cada vez que se inventa una nueva capability

### Migración backward

Seed en migración 008 para agentes existentes:

```sql
INSERT INTO agent_capabilities (agent_id, capability_name, is_active, config_json)
SELECT id, 'order', 1, '{}' FROM agents;
```

---

## Fase 1: BaseCapability + CapabilityRegistry + Refactor OrderState

### Objetivo

Abstraer el concepto de "state machine del negocio" en una interfaz genérica, y convertir `OrderState` en la primera implementación.

### Nuevo archivo: `core/capabilities.py`

```python
from abc import ABC, abstractmethod
import json
import re
from typing import Any

class BaseCapability(ABC):
    name: str
    tag_patterns: dict[str, re.Pattern]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    async def format_for_context(self, phone: str, config: dict[str, Any]) -> str | None:
        """Inject business state into LLM context. Return None if no state to inject."""

    @abstractmethod
    async def parse_tags(self, phone: str, text: str, config: dict[str, Any]) -> str:
        """Extract structured tags from LLM response, mutate state, return cleaned text."""

    @abstractmethod
    async def clear(self, phone: str, config: dict[str, Any]) -> None:
        """Reset state on session timeout."""

    @abstractmethod
    def get_prompt_instructions(self, config: dict[str, Any]) -> str:
        """Return system prompt instructions for this capability's tags."""


class CapabilityRegistry:
    _capabilities: dict[str, type[BaseCapability]] = {}

    def register(self, cls: type[BaseCapability]) -> None:
        self._capabilities[cls.name] = cls

    def get_class(self, name: str) -> type[BaseCapability] | None:
        return self._capabilities.get(name)

    def list_available(self) -> list[str]:
        return list(self._capabilities.keys())

    async def resolve(self, agent_id: int) -> list[BaseCapability]:
        from db.database import get_db
        db = await get_db()
        rows = await db.get_agent_capabilities(agent_id)
        instances: list[BaseCapability] = []
        for row in rows:
            if row["is_active"]:
                cls = self._capabilities.get(row["capability_name"])
                if cls:
                    config = json.loads(row["config_json"])
                    instances.append(cls(config=config))
        return instances


registry = CapabilityRegistry()
```

### Refactor de `OrderState` → `OrderCapability`

- Nuevo archivo: `core/capabilities/order.py`
- Clase `OrderCapability(BaseCapability)` con `name = "order"`
- Los métodos existentes (`format_for_context`, `parse_tags`, `clear`) se convierten en implementaciones de la interfaz
- `tag_patterns = {"ORDER_ADD": ORDER_TAG_RE, "ORDER_REMOVE": ORDER_REMOVE_RE, "ORDER_CLEAR": ORDER_CLEAR_RE}`
- `config` determina de dónde sacar el menú (`"menu_source": "db"` vs `"menu_source": "json"`)
- `get_prompt_instructions()` genera las instrucciones de tags con las claves del menú actual
- **Cero cambio funcional** — es puramente estructural
- `core/order_state.py` queda como wrapper de backward compat: `from core.capabilities.order import OrderCapability; order_state = OrderCapability()`

### Cambios en `db/models.py`

```python
@dataclass
class AgentCapability:
    id: int | None = None
    agent_id: int = 0
    capability_name: str = ""
    is_active: int = 1
    config_json: str = "{}"
    created_at: str | None = None
    updated_at: str | None = None
```

+ `row_to_agent_capability()` mapper

### Cambios en `db/database.py`

| Método | Firma | Descripción |
|--------|-------|-------------|
| `get_agent_capabilities` | `async def get_agent_capabilities(self, agent_id: int) -> list[Row]` | `SELECT * FROM agent_capabilities WHERE agent_id=?` |
| `upsert_agent_capability` | `async def upsert_agent_capability(self, ac: AgentCapability) -> int` | `INSERT OR REPLACE INTO agent_capabilities ...` |
| `delete_agent_capability` | `async def delete_agent_capability(self, agent_id: int, capability_name: str) -> None` | `DELETE FROM agent_capabilities WHERE agent_id=? AND capability_name=?` |

### Migración 008

```sql
CREATE TABLE IF NOT EXISTS agent_capabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL,
    capability_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    UNIQUE(agent_id, capability_name)
);

CREATE INDEX idx_agent_capabilities_agent ON agent_capabilities(agent_id);
CREATE INDEX idx_agent_capabilities_active ON agent_capabilities(agent_id, is_active);

INSERT INTO agent_capabilities (agent_id, capability_name, is_active, config_json)
SELECT id, 'order', 1, '{}' FROM agents;
```

---

## Fase 2: HITL Router + Memory + Sessions Dinámicos

### Objetivo

El HITL router, memory manager y session manager ya no llaman a `order_state` directamente. Llaman a las capabilities que el agente activo declara.

### Cambios en `core/hitl_router.py`

Antes (línea 172):
```python
response_text = await order_state.parse_tags(phone, response_text)
```

Después:
```python
from core.capabilities import registry

capabilities = await registry.resolve(conv.agent_id)
for cap in capabilities:
    response_text = await cap.parse_tags(phone, response_text, cap.config)
```

### Cambios en `core/memory.py`

Antes (línea 49):
```python
order_context = await order_state.format_for_context(phone)
if order_context:
    context.append({"role": "system", "content": order_context})
```

Después:
```python
from core.capabilities import registry

capabilities = await registry.resolve(agent_id)
for cap in capabilities:
    ctx = await cap.format_for_context(phone, cap.config)
    if ctx:
        context.append({"role": "system", "content": ctx})
```

Nota: `build_context()` necesita recibir `agent_id` como parámetro adicional. Se propaga desde `hitl_router._process_inbound_message_inner()`.

### Cambios en `core/sessions.py`

Antes (línea 36):
```python
await order_state.clear(phone)
```

Después:
```python
from core.capabilities import registry

capabilities = await registry.resolve(conv.agent_id)
for cap in capabilities:
    await cap.clear(phone, cap.config)
```

Nota: `sessions.py` ya tiene acceso a `conv` con `conv.agent_id`.

### Cambios en `core/inference.py`

Al construir el system_prompt, se apendan las instrucciones de cada capability:

```python
from core.capabilities import registry

capabilities = await registry.resolve(agent_id)
for cap in capabilities:
    instructions = cap.get_prompt_instructions(cap.config)
    if instructions:
        system_prompt += "\n\n" + instructions
```

Esto reemplaza las instrucciones de ORDER_ADD/REMOVE/CLEAR que hoy están hardcodeadas en el system_prompt del agente seed. El emprendedor escribe la personalidad y las reglas de negocio; las instrucciones técnicas de tags se inyectan automáticamente.

### Cache de capabilities

`registry.resolve()` hace una DB query por cada mensaje. Para evitar N+1:

- `InferenceEngine` cachea las capabilities junto con el agent (mismo TTL de 60s)
- `hitl_router` obtiene las capabilities desde `inference_engine._current_capabilities` después de `generate()`
- `memory_manager.build_context()` recibe las capabilities como parámetro desde `hitl_router` en vez de resolverlas independientemente

Flujo optimizado:
```
hitl_router.process_inbound_message():
  1. capabilities = await registry.resolve(conv.agent_id)  # 1 DB query
  2. history = await memory_manager.build_context(phone, text, capabilities=capabilities)  # sin DB extra
  3. response = await inference_engine.generate(text, history, agent_id, capabilities=capabilities)  # sin DB extra
  4. for cap in capabilities: response = await cap.parse_tags(phone, response, cap.config)
```

---

## Fase 3a: AppointmentCapability

### Objetivo

Capability para negocios basados en citas: dentista, abogado, peluquero, mecánico, etc.

### Nuevo archivo: `core/capabilities/appointment.py`

```python
class AppointmentCapability(BaseCapability):
    name = "appointment"
    tag_patterns = {
        "APPOINTMENT_ADD": re.compile(r"\[APPOINTMENT_ADD:([0-9-]+):([0-9:]+):([a-z_0-9]+)\]"),
        "APPOINTMENT_CANCEL": re.compile(r"\[APPOINTMENT_CANCEL:([0-9-]+):([0-9:]+)\]"),
        "APPOINTMENT_AVAILABLE": re.compile(r"\[APPOINTMENT_AVAILABLE:([0-9-]+)\]"),
    }
```

### `config_json` schema

```json
{
    "business_hours": {
        "mon-fri": "09:00-18:00",
        "sat": "10:00-14:00",
        "sun": "closed"
    },
    "slot_duration_minutes": 30,
    "services": [
        {"key": "limpieza", "name": "Limpieza dental", "duration_override": 45},
        {"key": "control", "name": "Control general", "duration_override": null}
    ],
    "timezone": "America/Santiago",
    "max_advance_days": 30
}
```

### Tags del LLM

| Tag | Formato | Efecto |
|-----|---------|--------|
| `[APPOINTMENT_ADD:date:time:service_key]` | `[APPOINTMENT_ADD:2025-05-05:14:00:limpieza]` | Crea cita confirmada |
| `[APPOINTMENT_CANCEL:date:time]` | `[APPOINTMENT_CANCEL:2025-05-05:14:00]` | Cancela cita existente |
| `[APPOINTMENT_AVAILABLE:date]` | `[APPOINTMENT_AVAILABLE:2025-05-05]` | LLM pide ver disponibilidad |

### Contexto inyectado

```
Citas del cliente:
- Lunes 5 May 14:00 — Limpieza dental (confirmada)
- Miércoles 7 May 10:00 — Control general (confirmada)

Próximas horas disponibles:
5 May: 11:00, 15:00, 16:30
6 May: 09:00, 10:30, 14:00
```

### `get_prompt_instructions()` output

```
GESTIÓN DE CITAS (OBLIGATORIO):
Cuando el cliente quiera agendar una cita, incluye al final de tu respuesta: [APPOINTMENT_ADD:fecha:hora:servicio]
- fecha en formato YYYY-MM-DD
- hora en formato HH:MM
- servicio: limpieza, control

Cuando el cliente cancele: [APPOINTMENT_CANCEL:fecha:hora]
Para consultar disponibilidad: [APPOINTMENT_AVAILABLE:fecha]

Los tags NO son visibles para el cliente.
```

### Tabla DB (migración 009)

```sql
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    service_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'confirmed',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

CREATE INDEX idx_appointments_phone ON appointments(phone);
CREATE INDEX idx_appointments_date ON appointments(date);
```

### Métodos DB nuevos

| Método | Firma |
|--------|-------|
| `save_appointment` | `async def save_appointment(self, phone, date, time, service_key, status) -> int` |
| `load_appointments` | `async def load_appointments(self, phone, status: str = "confirmed") -> list[Row]` |
| `cancel_appointment` | `async def cancel_appointment(self, phone, date, time) -> None` |
| `get_available_slots` | `async def get_available_slots(self, date, business_hours, slot_duration) -> list[str]` |

---

## Fase 3b: MembershipCapability

### Objetivo

Capability para negocios basados en membresías/planes: gym, SaaS, club, cowork, etc.

### Nuevo archivo: `core/capabilities/membership.py`

```python
class MembershipCapability(BaseCapability):
    name = "membership"
    tag_patterns = {
        "MEMBERSHIP_CHECK": re.compile(r"\[MEMBERSHIP_CHECK\]"),
        "MEMBERSHIP_PLAN": re.compile(r"\[MEMBERSHIP_PLAN:([a-z_0-9]+)\]"),
        "MEMBERSHIP_CANCEL": re.compile(r"\[MEMBERSHIP_CANCEL\]"),
    }
```

### `config_json` schema

```json
{
    "plans_source": "db",
    "allow_free_trial": true,
    "trial_days": 7,
    "billing_cycle": "monthly",
    "currency": "CLP"
}
```

### Tags del LLM

| Tag | Formato | Efecto |
|-----|---------|--------|
| `[MEMBERSHIP_CHECK]` | `[MEMBERSHIP_CHECK]` | Consultar estado de membresía |
| `[MEMBERSHIP_PLAN:plan_key]` | `[MEMBERSHIP_PLAN:premium]` | Cliente elige un plan |
| `[MEMBERSHIP_CANCEL]` | `[MEMBERSHIP_CANCEL]` | Cliente cancela membresía |

### Contexto inyectado

```
Membresía del cliente:
- Plan: Premium Mensual
- Inicio: 2025-01-15
- Próximo cobro: 2025-05-15
- Estado: Activa
```

### Tablas DB (migración 010)

```sql
CREATE TABLE IF NOT EXISTS memberships (
    phone TEXT PRIMARY KEY,
    plan_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT NOT NULL,
    next_billing TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

CREATE TABLE IF NOT EXISTS plans (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    billing_cycle TEXT NOT NULL DEFAULT 'monthly',
    features TEXT NOT NULL DEFAULT '[]',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Métodos DB nuevos

| Método | Firma |
|--------|-------|
| `load_membership` | `async def load_membership(self, phone) -> Row \| None` |
| `save_membership` | `async def save_membership(self, phone, plan_key, status, started_at, next_billing) -> None` |
| `cancel_membership` | `async def cancel_membership(self, phone) -> None` |
| `load_plans` | `async def load_plans(self) -> list[Row]` |
| `upsert_plan` | `async def upsert_plan(self, key, name, price, billing_cycle, features) -> None` |

---

## Fase 3c: LeadCapability

### Objetivo

Capability para negocios basados en funnel de leads: inmobiliaria, agencia, consultor, etc.

### Nuevo archivo: `core/capabilities/lead.py`

```python
class LeadCapability(BaseCapability):
    name = "lead"
    tag_patterns = {
        "LEAD_UPDATE": re.compile(r"\[LEAD_UPDATE:([a-z_0-9]+):([^\]]+)\]"),
        "LEAD_STAGE": re.compile(r"\[LEAD_STAGE:([a-z_0-9]+)\]"),
    }
```

### `config_json` schema

```json
{
    "stages": ["interesado", "calificado", "visita", "propuesta", "cerrado"],
    "fields": ["presupuesto", "zona", "tipo_propiedad", "dormitorios"],
    "currency": "CLP"
}
```

### Tags del LLM

| Tag | Formato | Efecto |
|-----|---------|--------|
| `[LEAD_UPDATE:field:value]` | `[LEAD_UPDATE:presupuesto:150M-200M]` | Actualiza dato del lead |
| `[LEAD_STAGE:stage]` | `[LEAD_STAGE:calificado]` | Avanza etapa del funnel |

### Contexto inyectado

```
Lead del cliente:
- Nombre: María
- Interés: Departamento 2 dorm
- Presupuesto: $150.000.000 - $200.000.000
- Zona: Providencia, Las Condes
- Etapa: Calificado
- Última interacción: Consultó por depto en Av. Providencia
```

### Tabla DB (migración 011)

```sql
CREATE TABLE IF NOT EXISTS leads (
    phone TEXT PRIMARY KEY,
    stage TEXT NOT NULL DEFAULT 'interesado',
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);
```

### Métodos DB nuevos

| Método | Firma |
|--------|-------|
| `load_lead` | `async def load_lead(self, phone) -> Row \| None` |
| `upsert_lead` | `async def upsert_lead(self, phone, stage, data_json) -> None` |

---

## Fase 4: Dashboard — Selector de Capabilities con Config

### Objetivo

El emprendedor puede activar/desactivar capabilities y configurarlas desde el dashboard sin tocar código.

### Cambios en `AgentEditor.tsx`

Agregar sección "Capabilities" con:

1. **Lista de capabilities disponibles** con toggle on/off
2. **Al activar una capability**, se muestra su formulario de configuración específica (generado dinámicamente desde el `config_json` schema)
3. **Al desactivar**, se pone `is_active=0` en vez de eliminar (conserva la config)

### Nuevo componente: `dashboard/components/CapabilityConfig.tsx`

Formulario dinámico que renderiza campos según el schema de cada capability:

- `business_hours` → time pickers por día
- `slot_duration_minutes` → number input
- `services` → lista editable con agregar/eliminar
- `stages` → lista editable con drag & drop de orden
- `fields` → checkboxes

### Nuevos endpoints API

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/capabilities` | Lista capabilities registradas en el registry (con su schema de config) |
| GET | `/api/agents/{id}/capabilities` | Capabilities del agente (JOIN con agent_capabilities) |
| PUT | `/api/agents/{id}/capabilities` | Upsert batch de capabilities con config |
| DELETE | `/api/agents/{id}/capabilities/{name}` | Eliminar capability del agente |

---

## Fase 5: Auto-inyección de Instrucciones en System Prompt

### Objetivo

El emprendedor nunca ve `[APPOINTMENT_ADD:...]` — eso se inyecta automáticamente al final del system prompt según las capabilities activas. El emprendedor solo escribe la personalidad y las reglas de negocio.

### Cómo funciona

Cada capability implementa `get_prompt_instructions(config) -> str` que devuelve la sección de instrucciones de tags.

En `core/inference.py`, al construir el system_prompt:

```python
capabilities = await registry.resolve(agent_id)
for cap in capabilities:
    instructions = cap.get_prompt_instructions(cap.config)
    if instructions:
        system_prompt += "\n\n" + instructions
```

### Separación de responsabilidades

| Quién | Escribe qué |
|-------|-------------|
| Emprendedor | Personalidad, tono, reglas de negocio, conocimiento del negocio |
| Sistema (auto) | Instrucciones de tags `[ORDER_ADD]`, `[APPOINTMENT_ADD]`, etc. |
| Sistema (auto) | Defensa contra prompt injection (`<customer_message>` tags) |

---

## Fase 6: Templates de Agente + Onboarding Guiado

### Objetivo

Un emprendedor nuevo no empieza desde cero — elige un template y customiza en 5 minutos.

### Tabla DB (migración 012)

```sql
CREATE TABLE IF NOT EXISTS agent_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    system_prompt_template TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '[]',
    fallback_responses TEXT NOT NULL DEFAULT '{}',
    config_schema TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Seed data

```sql
INSERT INTO agent_templates (name, description, system_prompt_template, capabilities, fallback_responses) VALUES
('food_truck', 'Bot para venta de comida',
 'Eres el asistente virtual de {{business_name}}. Vendes: {{products}}. Responde en español chileno, amable y directo.',
 '[{"name": "order", "config": {"menu_source": "db", "currency": "CLP"}}]',
 '{"greeting": "¡Hola! ¿Qué te gustaría ordenar?", "default": "¿En qué puedo ayudarte?"}'),

('dentista', 'Bot para consulta dental',
 'Eres la asistente virtual de {{business_name}}. Ayudas a los pacientes a agendar citas, consultar horarios y responder preguntas sobre servicios dentales.',
 '[{"name": "appointment", "config": {"slot_duration_minutes": 30, "services": ["limpieza", "control", "blanqueamiento"]}}]',
 '{"greeting": "¡Hola! ¿Deseas agendar una cita?", "default": "¿En qué puedo ayudarte?"}'),

('gym', 'Bot para gimnasio',
 'Eres la asistente virtual de {{business_name}}. Ayudas a los miembros con planes, horarios y estado de membresía.',
 '[{"name": "membership", "config": {"allow_free_trial": true, "trial_days": 7}}]',
 '{"greeting": "¡Hola! ¿Te interesa conocer nuestros planes?", "default": "¿En qué puedo ayudarte?"}'),

('inmobiliaria', 'Bot para inmobiliaria',
 'Eres la asistente virtual de {{business_name}}. Ayudas a los clientes a encontrar propiedades según sus necesidades.',
 '[{"name": "lead", "config": {"stages": ["interesado", "calificado", "visita", "propuesta", "cerrado"], "fields": ["presupuesto", "zona", "tipo_propiedad", "dormitorios"]}}]',
 '{"greeting": "¡Hola! ¿Buscas una propiedad?", "default": "¿En qué puedo ayudarte?"}');
```

### Endpoint

| Método | Ruta | Body | Descripción |
|--------|------|------|-------------|
| GET | `/api/templates` | — | Lista templates disponibles |
| POST | `/api/agents/from-template` | `{template_id, fields: {"business_name": "Dr. Pérez", ...}}` | Crea agente completo desde template |

### Flujo del dashboard

1. Emprendedor selecciona "Dentista"
2. Se le pide: nombre del negocio, horarios, servicios, precios
3. Se genera un agente completo con el template + las capabilities correctas
4. En 5 minutos tiene un bot funcional

---

## Mapa Completo de Cambios por Archivo

| Archivo | Cambio | Fase |
|---------|--------|------|
| `core/capabilities.py` | **NUEVO** — BaseCapability, CapabilityRegistry | 1 |
| `core/capabilities/order.py` | **NUEVO** — OrderCapability (refactor de order_state.py) | 1 |
| `core/capabilities/appointment.py` | **NUEVO** — AppointmentCapability | 3a |
| `core/capabilities/membership.py` | **NUEVO** — MembershipCapability | 3b |
| `core/capabilities/lead.py` | **NUEVO** — LeadCapability | 3c |
| `core/order_state.py` | Wrapper de backward compat → importa de capabilities/order.py | 1 |
| `core/hitl_router.py` | Reemplazar `order_state.parse_tags` → loop de capabilities | 2 |
| `core/memory.py` | Reemplazar `order_state.format_for_context` → loop de capabilities | 2 |
| `core/sessions.py` | Reemplazar `order_state.clear` → loop de capabilities | 2 |
| `core/inference.py` | Inyectar prompt instructions de capabilities | 2 |
| `db/models.py` | Agregar `AgentCapability` dataclass + `row_to_agent_capability` | 1 |
| `db/database.py` | Agregar `get_agent_capabilities`, `upsert_agent_capability`, `delete_agent_capability` + métodos por capability | 1, 3a-3c |
| `db/migrations/008_agent_capabilities.sql` | **NUEVO** — tabla agent_capabilities + seed | 1 |
| `db/migrations/009_appointments.sql` | **NUEVO** — tabla appointments | 3a |
| `db/migrations/010_memberships.sql` | **NUEVO** — tablas memberships + plans | 3b |
| `db/migrations/011_leads.sql` | **NUEVO** — tabla leads | 3c |
| `db/migrations/012_agent_templates.sql` | **NUEVO** — tabla agent_templates + seed | 6 |
| `routers/agents.py` | Endpoints de capabilities + templates | 4, 6 |
| `routers/capabilities.py` | **NUEVO** — endpoints GET /api/capabilities | 4 |
| `dashboard/components/AgentEditor.tsx` | Selector de capabilities + config forms | 4 |
| `dashboard/components/CapabilityConfig.tsx` | **NUEVO** — formularios dinámicos por capability | 4 |
| `dashboard/components/TemplateSelector.tsx` | **NUEVO** — selector de templates para onboarding | 6 |
| `tests/test_capabilities.py` | **NUEVO** — tests del registry, resolve, BaseCapability | 1 |
| `tests/test_appointment.py` | **NUEVO** — tests de AppointmentCapability | 3a |
| `tests/test_membership.py` | **NUEVO** — tests de MembershipCapability | 3b |
| `tests/test_lead.py` | **NUEVO** — tests de LeadCapability | 3c |
| Tests existentes | Actualizar mocks de order_state → capabilities | 2 |
| `CONTEXT.md`, `ROADMAP.md`, `AGENTS.md` | Actualizar documentación | cada fase |

---

## Riesgos y Mitigaciones

| Riesgo | Mitigación |
|--------|-----------|
| **Performance**: `registry.resolve()` hace DB query por cada mensaje | Cache de capabilities en `InferenceEngine` con mismo TTL de 60s que el agent. `hitl_router` pasa capabilities a memory/inference en vez de resolver independientemente |
| **Capability no registrada**: Un agente tiene `capability_name="appointment"` pero no hay clase registrada | `registry.resolve()` ignora silenciosamente las no encontradas, loggea warning |
| **Tags colisionan**: Dos capabilities usan el mismo tag | Cada capability define sus propios prefijos (`ORDER_`, `APPOINTMENT_`, `MEMBERSHIP_`, `LEAD_`) — no hay colisión posible |
| **Session clear sin agent_id**: `sessions.py` necesita agent_id | `sessions.py` ya tiene `conv` → `conv.agent_id` → resolver capabilities |
| **Migración backward**: Agentes existentes sin `agent_capabilities` row | Seed en migración 008: INSERT para todos los agentes existentes con capability `"order"` |
| **LLM emite tags de capability no activa**: El system prompt viejo tenía ORDER tags pero el agente nuevo no tiene la capability | Auto-inyección (Fase 5) garantiza que solo se inyectan instrucciones de capabilities activas. Tags no reconocidos por ningún handler se ignoran silenciosamente |

---

## Orden de Ejecución Estricto

```
Fase 1 (BaseCapability + Registry + OrderCapability + agent_capabilities table)
  ↓
Fase 2 (HITL Router + Memory + Sessions + Inference dinámicos)
  ↓
Fase 3a / 3b / 3c (en paralelo — Appointment / Membership / Lead)
  ↓
Fase 4 (Dashboard — selector de capabilities + config)
  ↓
Fase 5 (Auto-inyección de instrucciones en system prompt)
  ↓
Fase 6 (Templates de agente + onboarding guiado)
```

Fases 1 y 2 son el núcleo — una vez que existen, agregar nuevas capabilities es mecánico. Las fases 3a/3b/3c son independientes entre sí. Las fases 4-6 son UX y pueden iterarse.

---

## Cómo se Vería el Flujo Completo Después

### Dentista

1. Emprendedor selecciona template "Dentista"
2. Ingresa nombre: "Clínica Dental Dr. Pérez", horarios, servicios
3. Sistema crea agente con `AppointmentCapability` activa
4. System prompt generado: personalidad del dentista + instrucciones de APPOINTMENT tags (auto-inyectadas)
5. Cliente escribe: "Quiero una hora para limpieza"
6. LLM responde: "¡Claro! Tengo horas disponibles el 5 de mayo a las 14:00. ¿Te funciona? [APPOINTMENT_ADD:2025-05-05:14:00:limpieza]"
7. `AppointmentCapability.parse_tags()` crea la cita, limpia el tag
8. Cliente recibe: "¡Claro! Tengo horas disponibles el 5 de mayo a las 14:00. ¿Te funciona?"

### Gym

1. Emprendedor selecciona template "Gym"
2. Ingresa nombre: "FitCenter", planes y precios
3. Sistema crea agente con `MembershipCapability` activa
4. Cliente escribe: "¿Cuánto cuesta el plan premium?"
5. LLM responde con info del plan + `[MEMBERSHIP_PLAN:premium]` si el cliente confirma
6. `MembershipCapability.parse_tags()` registra la membresía

### Inmobiliaria

1. Emprendedor selecciona template "Inmobiliaria"
2. Ingresa nombre, zonas, tipos de propiedad
3. Sistema crea agente con `LeadCapability` activa
4. Cliente escribe: "Busco depto 2 dorm en Providencia, presupuesto 150-200M"
5. LLM responde + `[LEAD_UPDATE:presupuesto:150M-200M][LEAD_UPDATE:zona:providencia][LEAD_UPDATE:tipo_propiedad:depto_2dorm]`
6. `LeadCapability.parse_tags()` actualiza el lead, limpia tags
7. Próximo mensaje: contexto ya tiene "Lead: presupuesto 150-200M, zona Providencia, depto 2 dorm, etapa: interesado"

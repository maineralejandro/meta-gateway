# 🧠 Plan de Implementación: Memoria por Capas (Layered Memory)

Este plan reemplaza el historial crudo de 20 mensajes por un sistema de **resumen progresivo + ventana reciente**, reduciendo el consumo de tokens y dando al LLM memoria de largo plazo.

---

## Fase 1: Capa de Persistencia

**Objetivo:** Crear la tabla y modelos para almacenar resúmenes y datos clave extraídos de la conversación.

1.  **Crear migración `db/migrations/003_conversation_memory.sql`**:
    ```sql
    CREATE TABLE IF NOT EXISTS conversation_memory (
        phone TEXT PRIMARY KEY,
        summary TEXT NOT NULL DEFAULT '',
        key_facts TEXT NOT NULL DEFAULT '[]',
        total_messages_summarized INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (phone) REFERENCES conversations(phone)
    );
    ```

2.  **Modificar `db/schema.sql`**:
    *   Agregar la tabla `conversation_memory` después de `escalation_events` (línea 50) y antes de los índices.
    *   Agregar índice: `CREATE INDEX IF NOT EXISTS idx_memory_phone ON conversation_memory(phone);`

3.  **Modificar `db/models.py`**:
    *   Agregar el dataclass después de `AgentDecision` (línea 69):
    ```python
    @dataclass
    class ConversationMemory:
        phone: str
        summary: str = ""
        key_facts: str = "[]"
        total_messages_summarized: int = 0
        updated_at: Optional[str] = None
    ```
    *   Agregar función de mapeo:
    ```python
    def row_to_memory(row) -> Optional[ConversationMemory]:
        if row is None:
            return None
        return ConversationMemory(
            phone=row["phone"],
            summary=row["summary"],
            key_facts=row["key_facts"],
            total_messages_summarized=row["total_messages_summarized"],
            updated_at=row["updated_at"],
        )
    ```

4.  **Modificar `db/database.py`**:
    *   Agregar import de `ConversationMemory` y `row_to_memory` en las importaciones (línea 6-14).
    *   Agregar los siguientes métodos a la clase `Database`, después de `get_decision_for_message` (línea 187):
    ```python
    # --- Memory Methods ---

    async def get_memory(self, phone: str) -> ConversationMemory | None:
        row = await self.fetchone(
            "SELECT * FROM conversation_memory WHERE phone=?",
            (phone,),
        )
        return row_to_memory(row)

    async def upsert_memory(self, phone: str, summary: str, key_facts: str, total_count: int):
        conn = await self._get_conn()
        await conn.execute(
            """INSERT INTO conversation_memory (phone, summary, key_facts, total_messages_summarized, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(phone) DO UPDATE SET
               summary=excluded.summary,
               key_facts=excluded.key_facts,
               total_messages_summarized=excluded.total_messages_summarized,
               updated_at=CURRENT_TIMESTAMP""",
            (phone, summary, key_facts, total_count),
        )
        await conn.commit()

    async def count_messages(self, phone: str) -> int:
        row = await self.fetchone(
            "SELECT COUNT(*) as cnt FROM messages WHERE phone=?",
            (phone,),
        )
        return row["cnt"] if row else 0
    ```

---

## Fase 2: Motor de Gestión de Memoria

**Objetivo:** Implementar la clase que construye el contexto óptimo y decide cuándo comprimir.

1.  **Crear `core/memory.py`**:
    ```python
    import json
    import asyncio
    from db.database import db
    from core.config import settings
    from openai import AsyncOpenAI
    import structlog

    logger = structlog.get_logger()

    WINDOW_SIZE = 8           # Mensajes recientes que van completos al LLM
    SUMMARIZE_THRESHOLD = 15  # Cada cuántos mensajes nuevos se genera resumen

    SUMMARY_PROMPT = """Eres un asistente de gestión de memoria. Actualiza el resumen de esta conversación de WhatsApp.

    RESUMEN ANTERIOR:
    {previous_summary}

    MENSAJES NUEVOS:
    {messages}

    INSTRUCCIONES:
    1. Genera un resumen conciso (máximo 3 frases) que combine el resumen anterior con la información nueva.
    2. Extrae datos clave del cliente en formato JSON: nombre, dirección, productos pedidos, monto, preferencias.
    3. Si un dato nuevo contradice uno anterior, usa el nuevo.

    Responde EXACTAMENTE con este formato JSON:
    {{"summary": "resumen aquí", "key_facts": ["dato1", "dato2", ...]}}"""


    class MemoryManager:
        def __init__(self):
            self._client = None

        def _get_client(self) -> AsyncOpenAI | None:
            available = bool(
                settings.LLM_API_KEY
                and not settings.LLM_API_KEY.startswith("nvapi-REPLACE")
            )
            if not available:
                return None
            if self._client is None:
                self._client = AsyncOpenAI(
                    api_key=settings.LLM_API_KEY,
                    base_url=settings.LLM_BASE_URL,
                )
            return self._client

        async def build_context(self, phone: str) -> list[dict]:
            """Construye la lista de mensajes para el LLM: resumen + ventana reciente."""
            memory = await db.get_memory(phone)
            recent_msgs = await db.get_messages(phone, limit=WINDOW_SIZE)

            context = []

            # 1. Inyectar resumen como contexto previo
            if memory and memory.summary:
                summary_text = f"Resumen de la conversación anterior:\n{memory.summary}"
                if memory.key_facts and memory.key_facts != "[]":
                    summary_text += f"\nDatos clave del cliente: {memory.key_facts}"
                context.append({"role": "system", "content": summary_text})

            # 2. Agregar mensajes recientes (filtrar media sin texto útil)
            for msg in recent_msgs:
                if msg.text and not msg.text.startswith("[") :
                    role = "user" if msg.direction == "inbound" else "assistant"
                    context.append({"role": role, "content": msg.text})
                elif msg.text and msg.text.startswith("[location]"):
                    # Ubicaciones sí tienen valor semántico
                    context.append({"role": "user", "content": msg.text})

            return context

        async def maybe_summarize(self, phone: str):
            """Comprime mensajes viejos en un resumen si se superó el umbral."""
            memory = await db.get_memory(phone)
            total = await db.count_messages(phone)
            already_summarized = memory.total_messages_summarized if memory else 0

            new_since_last = total - already_summarized
            if new_since_last < SUMMARIZE_THRESHOLD:
                return  # No hay suficientes mensajes nuevos

            client = self._get_client()
            if not client:
                logger.warning("memory_summarize_skipped_no_llm", phone=phone)
                return

            # Obtener los mensajes que aún no se han resumido
            # (todos menos los últimos WINDOW_SIZE que quedan como contexto vivo)
            all_msgs = await db.get_messages(phone, limit=total)
            msgs_to_summarize = all_msgs[:-WINDOW_SIZE] if len(all_msgs) > WINDOW_SIZE else all_msgs

            # Formatear mensajes para el prompt
            formatted = []
            for msg in msgs_to_summarize:
                prefix = "Cliente" if msg.direction == "inbound" else "Bot"
                formatted.append(f"{prefix}: {msg.text or '[media]'}")
            messages_text = "\n".join(formatted[-30:])  # Cap a 30 msgs para no explotar tokens

            previous_summary = memory.summary if memory else "Sin resumen previo."

            try:
                response = await client.chat.completions.create(
                    model=settings.LLM_MODEL,
                    max_tokens=300,
                    messages=[{
                        "role": "user",
                        "content": SUMMARY_PROMPT.format(
                            previous_summary=previous_summary,
                            messages=messages_text,
                        ),
                    }],
                )

                raw = response.choices[0].message.content.strip()
                result = json.loads(raw)
                summary = result.get("summary", previous_summary)
                key_facts = json.dumps(result.get("key_facts", []), ensure_ascii=False)

                await db.upsert_memory(phone, summary, key_facts, total)
                logger.info(
                    "memory_summarized",
                    phone=phone,
                    total_messages=total,
                    summary_length=len(summary),
                )
            except Exception as e:
                logger.error("memory_summarize_error", phone=phone, error=str(e))


    memory_manager = MemoryManager()
    ```

> [!IMPORTANT]
> **Costo de tokens**: `maybe_summarize` hace UNA llamada LLM extra cada ~15 mensajes, con max_tokens=300. El input son ~30 mensajes formateados. Costo estimado: ~800 tokens input + 300 output = ~1100 tokens por ciclo de resumen. Mucho más barato que enviar 20 mensajes completos en cada request.

---

## Fase 3: Integración en el Flujo de Mensajes

**Objetivo:** Reemplazar la carga manual de historial en `hitl_router.py` por el sistema de memoria.

1.  **Modificar `core/hitl_router.py`**:
    *   Agregar import en la cabecera (línea 1-6):
    ```python
    from core.memory import memory_manager
    ```
    *   **Reemplazar las líneas 66-70** (carga manual de historial):
    ```python
    # ANTES (líneas 66-70):
    history_rows = await db.get_messages(phone, limit=20)
    history = []
    for msg in history_rows:
        role = "user" if msg.direction == "inbound" else "assistant"
        history.append({"role": role, "content": msg.text or ""})

    # DESPUÉS:
    history = await memory_manager.build_context(phone)
    ```
    *   **Agregar llamada a resumen** después de que el bot responde exitosamente. Insertar después de la línea 157 (`logger.info("bot_replied", phone=phone)`):
    ```python
    # Disparar resumen en background (no bloquea la respuesta)
    asyncio.create_task(memory_manager.maybe_summarize(phone))
    ```
    *   Agregar `import asyncio` si no está ya importado (verificar — no está en hitl_router.py actualmente).

2.  **Verificar `core/inference.py`**:
    *   No requiere cambios. El `history` que recibe `generate()` en línea 46 ahora contiene el resumen como un mensaje `system` adicional + los mensajes recientes. La línea 76-77 los inyecta correctamente:
    ```python
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)  # ← El resumen de memoria entra aquí
    ```
    *   **Punto a verificar**: Si `history` contiene un mensaje con `role: "system"` (el resumen), el LLM recibirá dos system prompts. Esto funciona bien con la mayoría de modelos (Llama 3.1, GPT-4, Qwen). Si el modelo no lo soporta, cambiar el role del resumen a `"user"` con un prefijo como `"[CONTEXTO PREVIO]:"`.

---

## Fase 4: Prompt de Resumen y Extracción

**Objetivo:** Asegurar que el prompt genera resúmenes de calidad.

1.  **El prompt ya está definido en `core/memory.py`** (Fase 2), pero aquí van las consideraciones:
    *   **Formato de salida**: JSON estricto con `summary` y `key_facts`. Si el modelo no responde con JSON válido, el `except` en `maybe_summarize` lo captura y se loguea sin romper el flujo.
    *   **Largo del resumen**: Máximo 3 frases. Esto equivale a ~50-80 tokens, vs los ~400+ tokens que consumían 20 mensajes crudos.
    *   **Key facts**: Datos estructurados como nombre, dirección, productos. Se guardan como JSON string en la DB para fácil consulta futura.
    *   **Resumen acumulativo**: Cada ciclo de resumen recibe el resumen anterior + mensajes nuevos. Esto permite que el resumen "crezca" en información sin perder contexto viejo.

2.  **Ejemplo de resumen esperado**:
    ```json
    {
        "summary": "El cliente Juan pidió 2 completos gigantes y una chorrillana para delivery a Av. Providencia 1234. Total $22.500. Esperando confirmación de tarifa de delivery.",
        "key_facts": [
            "Nombre: Juan",
            "Dirección: Av. Providencia 1234",
            "Pedido: 2 completos gigantes ($9.600), 1 chorrillana ($8.900)",
            "Total parcial: $22.500 (sin delivery)"
        ]
    }
    ```

---

## Fase 5: Pruebas

1.  **Crear `tests/test_memory.py`**:

    *   **Test `build_context` sin memoria previa**:
        *   Insertar 5 mensajes en la DB para un teléfono.
        *   Llamar a `build_context(phone)`.
        *   Verificar que retorna exactamente 5 mensajes con roles correctos (`user`/`assistant`).
        *   Verificar que NO hay mensaje de resumen al inicio.

    *   **Test `build_context` con memoria existente**:
        *   Insertar un registro en `conversation_memory` con `summary="Cliente pidió completo"`.
        *   Insertar 3 mensajes recientes.
        *   Llamar a `build_context(phone)`.
        *   Verificar que el primer elemento es `role: "system"` con el resumen.
        *   Verificar que le siguen los 3 mensajes recientes.

    *   **Test `build_context` filtra media**:
        *   Insertar un mensaje con `text="[image]"` y otro con `text="Hola"`.
        *   Verificar que `build_context` retorna solo el mensaje de texto.

    *   **Test `maybe_summarize` no actúa bajo umbral**:
        *   Insertar 10 mensajes (menor que `SUMMARIZE_THRESHOLD=15`).
        *   Llamar a `maybe_summarize(phone)`.
        *   Verificar que `conversation_memory` sigue vacía.

    *   **Test `maybe_summarize` actúa sobre umbral**:
        *   Insertar 16 mensajes.
        *   Mockear la respuesta del LLM con un JSON válido.
        *   Llamar a `maybe_summarize(phone)`.
        *   Verificar que `conversation_memory` tiene el resumen y `total_messages_summarized=16`.

    *   **Test `maybe_summarize` maneja error de LLM**:
        *   Mockear el LLM para que lance una excepción.
        *   Verificar que `maybe_summarize` no lanza error (lo captura) y `conversation_memory` queda vacía.

2.  **Test de integración**:
    *   Simular el flujo completo: enviar 20 mensajes via webhook mockado → verificar que `conversation_memory` se actualiza → verificar que `build_context` retorna resumen + 8 mensajes recientes.

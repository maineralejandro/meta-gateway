import asyncio
import os
import json
import sys

# Asegurar que el directorio raíz esté en el path
sys.path.append(os.getcwd())

from db.database import db, init_db, close_db
from core.memory import memory_manager
from unittest.mock import AsyncMock

async def run_validation():
    print("Iniciando validacion de Fase 5: Memoria por Capas\n")
    
    # Configuración de base de datos de prueba única
    os.environ["DB_DIR"] = "./tests/data"
    os.environ["DB_NAME"] = "val_memory_unique.db"
    os.environ["DB_PATH"] = "./tests/data/val_memory_unique.db"
    os.makedirs("./tests/data", exist_ok=True)
    
    if os.path.exists("./tests/data/val_memory_unique.db"):
        try:
            os.remove("./tests/data/val_memory_unique.db")
        except:
            pass
    
    await init_db()
    await db.execute("PRAGMA busy_timeout = 10000")
    
    # Cargar esquema manual para asegurar tablas
    with open("db/schema.sql", "r") as f:
        schema = f.read()
        await db._conn.executescript(schema)
        await db.commit()
    
    # Insertar agente y conversación
    await db.execute("INSERT OR IGNORE INTO agents (id, name, system_prompt) VALUES (1, 'Agente Prueba', 'Prompt')")
    phone = "+56912345678"
    await db.execute("INSERT OR IGNORE INTO conversations (phone, state, agent_id) VALUES (?, 'BOT_ACTIVE', 1)", (phone,))
    await db.commit()
    
    print("--- 1. Probando build_context (Mensajes Recientes) ---")
    await db.execute("INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', 'Hola')", (phone,))
    await db.execute("INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', '[image]')", (phone,)) # Debería filtrarse
    await db.execute("INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', '[location] Santiago')", (phone,))
    await db.commit()
    
    context = await memory_manager.build_context(phone)
    print(f"Mensajes en contexto: {len(context)}")
    for m in context:
        print(f"  [{m['role']}]: {m['content']}")
    
    # Validación
    assert len(context) == 2, "Debería haber 2 mensajes (Hola y location)"
    print("OK: build_context funciona y filtra media correctamente.\n")
    
    print("--- 2. Probando maybe_summarize (Umbral de Resumen) ---")
    # Insertar mensajes hasta llegar a 16 (Threshold = 15)
    for i in range(14):
        await db.execute("INSERT INTO messages (phone, direction, source, text) VALUES (?, 'inbound', 'customer', ?)", (phone, f"Mensaje extra {i}"))
    await db.commit()
    
    # Mockear el cliente LLM para el resumen
    memory_manager._get_client = lambda: AsyncMock()
    mock_client = memory_manager._get_client()
    
    # Crear la estructura de respuesta mockeada
    mock_message = AsyncMock()
    mock_message.content = json.dumps({
        "summary": "El cliente saludó y envió su ubicación en Santiago. Es una prueba de memoria.",
        "key_facts": ["Ubicación: Santiago", "Estado: Validando"]
    })
    
    mock_choice = AsyncMock()
    mock_choice.message = mock_message
    
    mock_response = AsyncMock()
    mock_response.choices = [mock_choice]
    
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    
    print("Disparando maybe_summarize...")
    await memory_manager.maybe_summarize(phone)
    
    # Verificar persistencia
    memory = await db.get_memory(phone)
    if memory and "prueba de memoria" in memory.summary:
        print(f"OK: Resumen guardado: {memory.summary}")
        print(f"OK: Datos clave: {memory.key_facts}")
        print(f"OK: Mensajes resumidos: {memory.total_messages_summarized}")
    else:
        print("ERROR: El resumen no se guardó correctamente.")
        exit(1)
    
    print("\n--- 3. Probando contexto con memoria persistida ---")
    context_with_mem = await memory_manager.build_context(phone)
    assert context_with_mem[0]["role"] == "system", "El primer mensaje debería ser el resumen (system)"
    assert "prueba de memoria" in context_with_mem[0]["content"]
    print("OK: build_context inyecta el resumen correctamente.\n")
    
    await close_db()
    print("Validacion de Fase 5 completada con éxito!")

if __name__ == "__main__":
    asyncio.run(run_validation())

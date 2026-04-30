# 🔧 Plan de Implementación: Sistema de Auto-Migración de Base de Datos

## Problema

La función `init_db()` actual en `db/database.py` (línea 273) ejecuta `schema.sql` con `executescript()`.
SQLite ignora los `CREATE TABLE IF NOT EXISTS` cuando la tabla ya existe, lo que significa que:
- Las nuevas columnas (`current_session_id` en `conversations`, `session_id` en `messages`) **nunca se añaden** a bases de datos preexistentes.
- Las nuevas tablas (`sessions`, `conversation_memory`) sí se crean porque usan `IF NOT EXISTS`.
- El resultado es un **desajuste fatal** entre el código Python y el esquema real de la DB.

## Solución

Implementar un sistema de migraciones versionado que:
1. Registre qué migraciones se han aplicado en una tabla `schema_migrations`.
2. Al arrancar, detecte migraciones pendientes y las ejecute en orden.
3. Sea idempotente: ejecutar dos veces nunca rompe nada.

## Contexto para el implementador

**Archivos clave que debes leer antes de empezar:**
- `db/database.py` — Contiene `init_db()` (línea 273-279) que será modificada.
- `db/schema.sql` — Estado deseado de la BD (99 líneas).
- `db/migrations/` — Carpeta con migraciones existentes: `001_agents.sql`, `002_sessions.sql`, `003_conversation_memory.sql`.

**Regla de oro:** Las migraciones existentes en `db/migrations/` solo crean tablas e índices.
Las columnas nuevas en tablas existentes (`current_session_id`, `session_id`) NO están cubiertas por ninguna migración.
Esto se debe corregir escribiendo las migraciones faltantes.

---

## Fase 1: Tabla de control de migraciones

**Objetivo:** Crear la infraestructura para trackear qué migraciones se han aplicado.

1. **Crear `db/migrations/000_baseline.sql`**:
   - Este archivo crea la tabla de control:
   ```sql
   CREATE TABLE IF NOT EXISTS schema_migrations (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       version TEXT NOT NULL UNIQUE,
       description TEXT NOT NULL DEFAULT '',
       applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   );
   ```
   - **IMPORTANTE**: Este archivo NO se registra a sí mismo en la tabla. Es el "bootstrap" que se ejecuta siempre de forma incondicional.

---

## Fase 2: Reescribir las migraciones existentes

**Objetivo:** Convertir las migraciones existentes en scripts idempotentes que cubran TODOS los cambios de esquema, incluyendo columnas nuevas en tablas existentes.

1. **Dejar `db/migrations/001_agents.sql`** tal cual está. Ya es idempotente con `IF NOT EXISTS`.

2. **Reescribir `db/migrations/002_sessions.sql`** para que además de crear la tabla `sessions`, añada las columnas faltantes:
   ```sql
   -- Crear tabla de sesiones
   CREATE TABLE IF NOT EXISTS sessions (
       id TEXT PRIMARY KEY,
       phone TEXT NOT NULL,
       started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       ended_at TIMESTAMP,
       end_reason TEXT,
       summary TEXT,
       message_count INTEGER DEFAULT 0,
       FOREIGN KEY (phone) REFERENCES conversations(phone)
   );
   CREATE INDEX IF NOT EXISTS idx_sessions_phone ON sessions(phone, started_at);

   -- Añadir columna current_session_id a conversations (si no existe)
   -- NOTA: SQLite no tiene IF NOT EXISTS para ALTER TABLE.
   -- La estrategia es intentar el ALTER y capturar el error en Python.
   ALTER TABLE conversations ADD COLUMN current_session_id TEXT REFERENCES sessions(id);

   -- Añadir columna session_id a messages (si no existe)
   ALTER TABLE messages ADD COLUMN session_id TEXT REFERENCES sessions(id);
   ```

3. **Dejar `db/migrations/003_conversation_memory.sql`** tal cual. Ya es idempotente con `IF NOT EXISTS`.

> [!IMPORTANT]
> SQLite NO soporta `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. La solución es que el runner de migraciones en Python capture el error `duplicate column name` y lo ignore silenciosamente. Esto se implementa en la Fase 3.

---

## Fase 3: Implementar el Migration Runner

**Objetivo:** Crear `db/migrator.py` con la lógica que ejecuta migraciones pendientes.

1. **Crear `db/migrator.py`** con la siguiente lógica:

   ```python
   import sqlite3
   import os
   import structlog
   from pathlib import Path

   logger = structlog.get_logger()

   MIGRATIONS_DIR = Path(__file__).parent / "migrations"

   def run_migrations(db_path: str):
       """
       Ejecuta todas las migraciones pendientes en orden.
       Esta función usa sqlite3 síncrono (no aiosqlite) porque se ejecuta
       durante el startup, ANTES de que el event loop esté disponible.
       """
       conn = sqlite3.connect(db_path)
       conn.execute("PRAGMA foreign_keys=OFF")  # Desactivar FK durante migraciones

       # 1. Bootstrap: crear tabla de control si no existe
       bootstrap = (MIGRATIONS_DIR / "000_baseline.sql").read_text()
       conn.executescript(bootstrap)

       # 2. Obtener migraciones ya aplicadas
       cursor = conn.execute("SELECT version FROM schema_migrations")
       applied = {row[0] for row in cursor.fetchall()}

       # 3. Descubrir archivos de migración (ordenados por nombre)
       migration_files = sorted(
           f for f in MIGRATIONS_DIR.glob("*.sql")
           if f.name != "000_baseline.sql"
       )

       # 4. Aplicar migraciones pendientes
       for migration_file in migration_files:
           version = migration_file.stem  # e.g., "001_agents"
           if version in applied:
               continue

           logger.info("applying_migration", version=version)
           sql = migration_file.read_text()

           # Ejecutar línea por línea para manejar ALTER TABLE que puede fallar
           for statement in sql.split(";"):
               statement = statement.strip()
               if not statement or statement.startswith("--"):
                   continue
               try:
                   conn.execute(statement)
               except sqlite3.OperationalError as e:
                   error_msg = str(e).lower()
                   # Ignorar errores de "columna ya existe" o "tabla ya existe"
                   if "duplicate column" in error_msg or "already exists" in error_msg:
                       logger.info("migration_skip_existing", statement=statement[:80], reason=str(e))
                       continue
                   raise  # Re-lanzar errores reales

           # Registrar migración como aplicada
           conn.execute(
               "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
               (version, f"Applied from {migration_file.name}")
           )
           conn.commit()
           logger.info("migration_applied", version=version)

       conn.execute("PRAGMA foreign_keys=ON")
       conn.close()
   ```

   **Puntos críticos de diseño:**
   - Se usa `sqlite3` síncrono, NO `aiosqlite`, porque `init_db` corre durante el startup antes del event loop.
   - `PRAGMA foreign_keys=OFF` durante migraciones para evitar errores de FK al crear tablas en orden arbitrario.
   - Los `ALTER TABLE` que fallan con "duplicate column" se ignoran silenciosamente (esto es la clave para la idempotencia).
   - Cada migración se registra en `schema_migrations` DESPUÉS de ejecutarse exitosamente.

---

## Fase 4: Reemplazar `init_db()`

**Objetivo:** Conectar el nuevo sistema de migraciones al ciclo de vida de la aplicación.

1. **Modificar `db/database.py`**, reemplazar la función `init_db()` actual (líneas 273-279):

   ```python
   async def init_db():
       from db.migrator import run_migrations
       os.makedirs(settings.DB_DIR, exist_ok=True)
       run_migrations(settings.DB_PATH)
       await db._get_conn()
   ```

   **Lo que se elimina:**
   - La línea `schema = SCHEMA_PATH.read_text()` — ya no se usa.
   - La línea `sync_conn = sqlite3.connect(settings.DB_PATH)` — el migrator lo maneja.
   - La línea `sync_conn.executescript(schema)` — reemplazada por `run_migrations`.
   - La línea `sync_conn.close()` — el migrator lo maneja.

   **Lo que se mantiene:**
   - `os.makedirs(settings.DB_DIR, exist_ok=True)` — necesario para crear el directorio.
   - `await db._get_conn()` — necesario para inicializar la conexión async.

> [!WARNING]
> NO elimines `db/schema.sql`. Sigue siendo útil como documentación del estado deseado y para los tests que crean DBs desde cero.

---

## Fase 5: Pruebas

**Objetivo:** Verificar que el sistema de migraciones funciona correctamente.

1. **Crear `tests/test_migrator.py`** con los siguientes tests:

   - **Test 1 — BD nueva desde cero**: Crear una BD vacía, ejecutar `run_migrations()`, verificar que TODAS las tablas existen y que `schema_migrations` tiene los registros correctos.

   - **Test 2 — BD legacy (sin migraciones previas)**: Crear una BD con solo las tablas originales (sin `sessions`, sin `conversation_memory`, sin columnas `current_session_id` ni `session_id`). Ejecutar `run_migrations()`. Verificar que las tablas y columnas nuevas se crearon correctamente.

   - **Test 3 — Idempotencia**: Ejecutar `run_migrations()` dos veces seguidas sobre la misma BD. Verificar que la segunda ejecución no produce errores y que `schema_migrations` no tiene duplicados.

   - **Test 4 — Migración parcial**: Simular una BD que ya tiene `001_agents` aplicada pero no `002` ni `003`. Verificar que solo se aplican las pendientes.

   **Estructura del test:**
   ```python
   import pytest
   import sqlite3
   import os
   import random
   from db.migrator import run_migrations

   @pytest.fixture
   def temp_db():
       path = f"./tests/data/migrator_test_{random.randint(10000,99999)}.db"
       os.makedirs("./tests/data", exist_ok=True)
       yield path
       if os.path.exists(path):
           os.remove(path)

   def test_fresh_db(temp_db):
       run_migrations(temp_db)
       conn = sqlite3.connect(temp_db)
       # Verificar que existen todas las tablas
       tables = {r[0] for r in conn.execute(
           "SELECT name FROM sqlite_master WHERE type='table'"
       ).fetchall()}
       assert "agents" in tables
       assert "sessions" in tables
       assert "conversation_memory" in tables
       assert "schema_migrations" in tables
       # Verificar columnas en conversations
       cols = {r[1] for r in conn.execute("PRAGMA table_info(conversations)")}
       assert "current_session_id" in cols
       conn.close()

   def test_idempotent(temp_db):
       run_migrations(temp_db)
       run_migrations(temp_db)  # Segunda vez
       conn = sqlite3.connect(temp_db)
       count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
       assert count == 3  # 001, 002, 003
       conn.close()
   ```

2. **Ejecutar los tests:**
   ```bash
   PYTHONPATH=. pytest tests/test_migrator.py -s
   ```

3. **Ejecutar TODOS los tests existentes** para confirmar que nada se rompe:
   ```bash
   PYTHONPATH=. pytest tests/ -s
   ```

---

## Fase 6: Commit y Push

1. **Commitear los cambios:**
   ```bash
   git add db/migrator.py db/migrations/000_baseline.sql db/migrations/002_sessions.sql db/database.py tests/test_migrator.py
   git commit -m "feat: implement versioned database migration system"
   git push origin develop
   ```

2. **Verificar que la aplicación arranca correctamente:**
   ```bash
   .\start_all.ps1
   ```
   - El log debe mostrar líneas de `applying_migration` para cada migración pendiente.
   - El dashboard debe cargar conversaciones sin error 500.

---

## Resumen de archivos

| Acción | Archivo | Descripción |
|--------|---------|-------------|
| **Crear** | `db/migrations/000_baseline.sql` | Tabla de control `schema_migrations` |
| **Crear** | `db/migrator.py` | Motor de migraciones |
| **Modificar** | `db/migrations/002_sessions.sql` | Añadir `ALTER TABLE` para columnas faltantes |
| **Modificar** | `db/database.py` | Reemplazar `init_db()` para usar el migrator |
| **Crear** | `tests/test_migrator.py` | Suite de pruebas |

> [!CAUTION]
> Este sistema NO elimina ni renombra columnas. Solo AÑADE tablas, columnas e índices.
> Para cambios destructivos futuros (DROP, RENAME), se necesitaría un approach más sofisticado con recreación de tablas.

import sqlite3
import re
import os
import structlog
from pathlib import Path

logger = structlog.get_logger()

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Regex to identify ALTER TABLE statements
ALTER_RE = re.compile(r"^\s*ALTER\s+TABLE", re.IGNORECASE)


def run_migrations(db_path: str):
    """
    Ejecuta todas las migraciones pendientes en orden.
    Esta función usa sqlite3 síncrono (no aiosqlite) porque se ejecuta
    durante el startup, ANTES de que el event loop esté disponible.

    Estrategia híbrida:
    - Las sentencias normales (CREATE TABLE, INSERT, CREATE INDEX) se ejecutan
      con executescript() que maneja múltiples sentencias.
    - Las sentencias ALTER TABLE se ejecutan individualmente con execute()
      para poder capturar y ignorar errores de "duplicate column".
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
        version = migration_file.stem  # e.g., "001_initial_schema"
        if version in applied:
            continue

        logger.info("applying_migration", version=version)
        sql = migration_file.read_text()

        # Separar sentencias ALTER TABLE de las demás
        alter_statements = []
        safe_statements = []

        for statement in sql.split(";"):
            stripped = statement.strip()
            if not stripped:
                continue
            # Eliminar líneas de comentarios para evaluar el contenido real
            lines = [l for l in stripped.split("\n") if not l.strip().startswith("--")]
            clean = "\n".join(lines).strip()
            if not clean:
                continue

            if ALTER_RE.match(clean):
                alter_statements.append(clean)
            else:
                safe_statements.append(stripped)

        # Ejecutar sentencias seguras (CREATE TABLE, INSERT, etc.) como bloque
        if safe_statements:
            safe_sql = ";\n".join(safe_statements) + ";"
            conn.executescript(safe_sql)

        # Ejecutar ALTER TABLE individualmente, capturando errores de columna duplicada
        for alter in alter_statements:
            try:
                conn.execute(alter)
            except sqlite3.OperationalError as e:
                error_msg = str(e).lower()
                if "duplicate column" in error_msg or "already exists" in error_msg:
                    logger.info("migration_skip_existing", statement=alter[:80], reason=str(e))
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

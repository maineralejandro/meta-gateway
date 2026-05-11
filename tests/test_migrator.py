import os
import random
import sqlite3
from contextlib import suppress

import pytest

from db.migrator import run_migrations


@pytest.fixture
def temp_db():
    path = f"./tests/data/migrator_test_{random.randint(10000,99999)}.db"
    os.makedirs("./tests/data", exist_ok=True)
    yield path
    if os.path.exists(path):
        with suppress(PermissionError):
            os.remove(path)

def test_fresh_db(temp_db):
    """Verifica que una BD nueva se crea con todas las tablas y columnas."""
    run_migrations(temp_db)
    conn = sqlite3.connect(temp_db)

    # Verificar que existen todas las tablas principales
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cursor.fetchall()}

    assert "agents" in tables
    assert "conversations" in tables
    assert "messages" in tables
    assert "sessions" in tables
    assert "conversation_memory" in tables
    assert "turns" in tables
    assert "schema_migrations" in tables

    # Verificar columnas críticas añadidas por ALTER TABLE
    cursor = conn.execute("PRAGMA table_info(conversations)")
    cols = {r[1] for r in cursor.fetchall()}
    assert "current_session_id" in cols

    cursor = conn.execute("PRAGMA table_info(messages)")
    cols = {r[1] for r in cursor.fetchall()}
    assert "session_id" in cols

    cursor = conn.execute("PRAGMA table_info(turns)")
    cols = {r[1] for r in cursor.fetchall()}
    assert "session_id" in cols

    conn.close()

def test_idempotent(temp_db):
    """Verifica que ejecutar migraciones dos veces no rompe nada."""
    run_migrations(temp_db)
    run_migrations(temp_db)  # Segunda vez

    conn = sqlite3.connect(temp_db)
    cursor = conn.execute("SELECT COUNT(*) FROM schema_migrations")
    count = cursor.fetchone()[0]

    # Debe haber 16 migraciones registradas (001-016)
    # 000_baseline no se registra a si misma
    assert count == 17
    conn.close()

def test_legacy_upgrade(temp_db):
    """Simula la BD de producción real: todas las tablas originales pero sin
    las columnas/tablas de sesiones ni memoria."""
    conn = sqlite3.connect(temp_db)
    # Esquema original completo (tal cual estaba antes de las migraciones)
    conn.executescript("""
        CREATE TABLE agents (
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
        CREATE TABLE conversations (
            phone TEXT PRIMARY KEY,
            contact_name TEXT,
            state TEXT DEFAULT 'BOT_ACTIVE',
            last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            requires_human_review INTEGER DEFAULT 0,
            unread_count INTEGER DEFAULT 0,
            sentiment_score REAL,
            confidence REAL,
            agent_id INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            direction TEXT NOT NULL,
            source TEXT NOT NULL,
            text TEXT,
            media_type TEXT,
            media_url TEXT,
            meta_message_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE escalation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            from_state TEXT NOT NULL,
            to_state TEXT NOT NULL,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE agent_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            phone TEXT NOT NULL,
            sentiment TEXT NOT NULL DEFAULT 'neutral',
            sentiment_score REAL DEFAULT 0.5,
            confidence REAL DEFAULT 0.5,
            llm_escalate INTEGER DEFAULT 0,
            escalate_reason TEXT,
            history_count INTEGER DEFAULT 0,
            agent_name TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO agents (name, system_prompt) VALUES ('Test Agent', 'test');
        INSERT INTO conversations (phone) VALUES ('56912345678');
    """)
    conn.close()

    # Ejecutar migrador sobre la BD legacy
    run_migrations(temp_db)

    # Verificar que las tablas nuevas se crearon
    conn = sqlite3.connect(temp_db)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cursor.fetchall()}
    assert "sessions" in tables
    assert "conversation_memory" in tables
    assert "turns" in tables
    assert "schema_migrations" in tables

    # Verificar que las columnas nuevas se añadieron
    cursor = conn.execute("PRAGMA table_info(conversations)")
    cols = {r[1] for r in cursor.fetchall()}
    assert "current_session_id" in cols

    cursor = conn.execute("PRAGMA table_info(messages)")
    cols = {r[1] for r in cursor.fetchall()}
    assert "session_id" in cols

    # Verificar que los datos existentes no se perdieron
    cursor = conn.execute("SELECT COUNT(*) FROM conversations")
    assert cursor.fetchone()[0] == 1

    conn.close()

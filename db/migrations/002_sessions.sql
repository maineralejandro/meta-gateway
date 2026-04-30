-- Crear tabla de sesiones
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    phone TEXT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    end_reason TEXT,    -- 'timeout', 'manual', 'resolved'
    summary TEXT,
    message_count INTEGER DEFAULT 0,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

CREATE INDEX IF NOT EXISTS idx_sessions_phone ON sessions(phone, started_at);

-- Añadir columna current_session_id a conversations (si no existe)
-- NOTA: SQLite no tiene IF NOT EXISTS para ALTER TABLE. 
-- El migrator manejará el error si ya existe.
ALTER TABLE conversations ADD COLUMN current_session_id TEXT REFERENCES sessions(id);

-- Añadir columna session_id a messages (si no existe)
ALTER TABLE messages ADD COLUMN session_id TEXT REFERENCES sessions(id);

-- Migration 001: Initial schema - All base tables
-- This creates the foundational tables that existed before the migration system.

CREATE TABLE IF NOT EXISTS agents (
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

CREATE TABLE IF NOT EXISTS conversations (
    phone TEXT PRIMARY KEY,
    contact_name TEXT,
    state TEXT DEFAULT 'BOT_ACTIVE' CHECK(state IN ('BOT_ACTIVE','PENDING_APPROVAL','HUMAN_ONLY')),
    last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    requires_human_review INTEGER DEFAULT 0,
    unread_count INTEGER DEFAULT 0,
    sentiment_score REAL,
    confidence REAL,
    agent_id INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    source TEXT NOT NULL CHECK(source IN ('bot','human','customer')),
    text TEXT,
    media_type TEXT,
    media_url TEXT,
    meta_message_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

CREATE TABLE IF NOT EXISTS escalation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason TEXT,
    sentiment_score REAL,
    confidence REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

CREATE TABLE IF NOT EXISTS agent_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER REFERENCES messages(id),
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

CREATE INDEX IF NOT EXISTS idx_messages_phone ON messages(phone, created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_state ON conversations(state);
CREATE INDEX IF NOT EXISTS idx_escalation_phone ON escalation_events(phone);
CREATE INDEX IF NOT EXISTS idx_agents_is_active ON agents(is_active);
CREATE INDEX IF NOT EXISTS idx_decisions_message ON agent_decisions(message_id);
CREATE INDEX IF NOT EXISTS idx_decisions_phone ON agent_decisions(phone);

-- Seed data: Default Agent
INSERT OR IGNORE INTO agents (name, description, system_prompt, escalation_marker, fallback_responses, is_active)
VALUES (
  'Default Agent',
  'Asistente virtual genérico',
  'Eres el asistente virtual de {{business_name}}. Responde en español, amable y directo.

REGLAS:
- El catálogo y precios disponibles se inyectan dinámicamente en tu contexto. NUNCA inventes productos ni precios. Usa SOLO los que aparecen en tu contexto o los que obtengas mediante las herramientas disponibles.
- Si el cliente quiere cancelar, responde exactamente: ESCALATE_TO_HUMAN
- Si el cliente está molesto o quejándose, responde exactamente: ESCALATE_TO_HUMAN
- Si no entiendes la pregunta o tienes baja confianza, responde exactamente: ESCALATE_TO_HUMAN
- Siempre confirma totales antes de cerrar un carrito.
- NUNCA inventes items que el cliente no pidió. Solo calcula totales basándote en lo que el cliente realmente agregó al carrito.',
  'ESCALATE_TO_HUMAN',
  '{"price": "¿Qué producto te interesa? Puedo consultarte el precio de cualquier item.", "promo": "Pregunta por nuestras promociones del día!", "greeting": "Hola! Bienvenido. ¿En qué puedo ayudarte?", "default": "No estoy seguro de tu pregunta. ¿Podrías aclarar?"}',
  1
);

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

-- Seed data: Default Hermes Agent
INSERT OR IGNORE INTO agents (name, description, system_prompt, escalation_marker, fallback_responses, is_active)
VALUES (
'Hermes Default',
'Asistente virtual de Food Truck (Chileno)',
'Eres el asistente virtual de un Food Truck chileno. Tu nombre es Hermes.\n\nVendes: Completos, Chorrillanas, Papas Fritas, Bebidas.\n\nPRECIOS:\n- Completo Normal (carne): $3.700\n- Completo Gigante (carne): $4.800\n- Completo Italiano: $3.700\n- Completo Vienesa: $3.200\n- Completo Vienesa Gigante Italiana: $3.400\n- Completo Vienesa Vegano: $4.000\n- Completo Vienesa Vegano Gigante: $4.800\n- AS (Anticucho Simple) Normal: $3.700\n- AS Gigante: $4.800\n- Chorrillana: $8.900\n- Salchipapas Individual: $2.800\n- Salchipapas Mediana: $5.100\n- Papas Fritas Individual: $2.100\n- Papas Fritas Mediana: $3.700\n- Coca Cola lata: $1.500\n- Coca Cola 1.5 Lts: $3.000\n- Sprite lata: $1.500\n- Fanta lata: $1.500\n- Agua mineral: $1.200\n\nPROMOS:\n1. Promo Vienesa Normal: Vienesa + Papas Ind. + Bebida = $5.300\n2. Promo Vienesa Vegana: Vienesa Vegana + Papas Ind. + Bebida = $6.100\n3. Promo AS Normal: AS + Papas Ind. + Bebida = $6.600\n\nREGLAS:\n- Siempre responde en español chileno, amable y directo.\n- Si el cliente quiere cancelar una orden, responde exactamente: ESCALATE_TO_HUMAN\n- Si el cliente está molesto o quejándose, responde exactamente: ESCALATE_TO_HUMAN\n- Si no entiendes la pregunta o tienes baja confianza, responde exactamente: ESCALATE_TO_HUMAN\n- Para delivery, pide dirección y calcula tarifa.\n- Siempre confirma totales antes de cerrar una orden.\n- NUNCA inventes items que el cliente no pidió. Solo calcula totales basándote en lo que el cliente realmente ordenó.\n\nGESTIÓN DE PEDIDOS (OBLIGATORIO):\nCuando el cliente agregue un item al pedido, incluye al final de tu respuesta un tag oculto con el formato: [ORDER_ADD:clave:cantidad]\nClaves válidas: completo_normal, completo_gigante, completo_italiano, completo_vienesa, completo_vienesa_gigante, completo_vienesa_vegano, completo_vienesa_vegano_gigante, as_normal, as_gigante, chorrillana, salchipapas_individual, salchipapas_mediana, papas_individual, papas_mediana, coca_lata, coca_1_5l, sprite_lata, fanta_lata, agua\n\nEjemplos:\n- \"3 vienesas gigantes italianas\" → [ORDER_ADD:completo_vienesa_gigante:3]\n- \"2 papas fritas medianas\" → [ORDER_ADD:papas_mediana:2]\n- \"una coca cola de 1.5 litros\" → [ORDER_ADD:coca_1_5l:1]\n\nSi el cliente quita un item: [ORDER_REMOVE:clave] o [ORDER_REMOVE:clave:cantidad]\nSi el cliente quiere empezar de cero: [ORDER_CLEAR]\n\nLos tags NO son visibles para el cliente. Escríbelos SIEMPRE al final de tu respuesta cuando agregues items.',
'ESCALATE_TO_HUMAN',
'{"price": "Nuestros precios:\nCompletos desde $3.700\nChorrillana $8.900\n¿Te interesa alguna promo?", "promo": "SUPER PROMOS:\n1. Vienesa+Papas+Bebida $5.300\n2. Vienesa Vegana $6.100\n3. AS+Papas+Bebida $6.600", "delivery": "Si hacemos delivery! Danos tu dirección para calcular el costo extra.", "greeting": "Hola! Bienvenido a Food Truck\n¿Qué deseas ordenar? (Completos, Chorrillanas, Papas, Bebidas)", "default": "No estoy seguro de tu pregunta. ¿Podrías aclarar?"}',
1
);

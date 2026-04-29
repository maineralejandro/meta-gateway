CREATE TABLE IF NOT EXISTS conversations (
    phone TEXT PRIMARY KEY,
    contact_name TEXT,
    state TEXT DEFAULT 'BOT_ACTIVE' CHECK(state IN ('BOT_ACTIVE','PENDING_APPROVAL','HUMAN_ONLY')),
    last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    requires_human_review INTEGER DEFAULT 0,
    unread_count INTEGER DEFAULT 0,
    sentiment_score REAL,
    confidence REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

CREATE INDEX IF NOT EXISTS idx_messages_phone ON messages(phone, created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_state ON conversations(state);
CREATE INDEX IF NOT EXISTS idx_escalation_phone ON escalation_events(phone);

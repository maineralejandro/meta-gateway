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
    current_session_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    FOREIGN KEY (current_session_id) REFERENCES sessions(id)
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
    session_id TEXT,
    correlation_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

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

CREATE TABLE IF NOT EXISTS conversation_memory (
    phone TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    key_facts TEXT NOT NULL DEFAULT '[]',
    total_messages_summarized INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

CREATE INDEX IF NOT EXISTS idx_messages_phone ON messages(phone, created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_state ON conversations(state);
CREATE INDEX IF NOT EXISTS idx_escalation_phone ON escalation_events(phone);
CREATE INDEX IF NOT EXISTS idx_agents_is_active ON agents(is_active);
CREATE INDEX IF NOT EXISTS idx_memory_phone ON conversation_memory(phone);
CREATE INDEX IF NOT EXISTS idx_sessions_phone ON sessions(phone, started_at);

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
    correlation_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_decisions_message ON agent_decisions(message_id);
CREATE INDEX IF NOT EXISTS idx_decisions_phone ON agent_decisions(phone);

CREATE TABLE IF NOT EXISTS carts (
    phone TEXT PRIMARY KEY,
    items_json TEXT NOT NULL DEFAULT '[]',
    total INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

CREATE INDEX IF NOT EXISTS idx_carts_phone ON carts(phone);

CREATE TABLE IF NOT EXISTS catalog_items (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    subcategory TEXT NOT NULL DEFAULT '',
    base_price INTEGER,
    is_available INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    size TEXT NOT NULL DEFAULT '',
    specifications TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_catalog_items_category ON catalog_items(category);

CREATE TABLE IF NOT EXISTS catalog_item_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL,
    label TEXT NOT NULL,
    price INTEGER NOT NULL,
    slug TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (item_key) REFERENCES catalog_items(key) ON DELETE CASCADE,
    UNIQUE(item_key, slug)
);

CREATE INDEX IF NOT EXISTS idx_catalog_variants_item_key ON catalog_item_variants(item_key);

CREATE TABLE IF NOT EXISTS catalog_options (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    category_scope TEXT NOT NULL DEFAULT '*',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS promotions (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    promotion_type TEXT NOT NULL CHECK(promotion_type IN ('fixed_price', 'percentage', 'bogo', 'bundle', 'flat_discount', 'other')) DEFAULT 'fixed_price',
    price INTEGER,
    display_text TEXT NOT NULL DEFAULT '',
    valid_days TEXT NOT NULL DEFAULT '[]',
    valid_from TEXT NOT NULL DEFAULT '',
    valid_to TEXT NOT NULL DEFAULT '',
    terms TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS promotion_items (
    promotion_key TEXT NOT NULL,
    item_key TEXT NOT NULL,
    promotion_price INTEGER,
    PRIMARY KEY (promotion_key, item_key),
    FOREIGN KEY (promotion_key) REFERENCES promotions(key) ON DELETE CASCADE,
    FOREIGN KEY (item_key) REFERENCES catalog_items(key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_promotion_items_promo ON promotion_items(promotion_key);
CREATE INDEX IF NOT EXISTS idx_promotion_items_item ON promotion_items(item_key);

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

CREATE INDEX IF NOT EXISTS idx_agent_capabilities_agent ON agent_capabilities(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_capabilities_active ON agent_capabilities(agent_id, is_active);

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

CREATE INDEX IF NOT EXISTS idx_appointments_phone ON appointments(phone);
CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(date);

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

CREATE TABLE IF NOT EXISTS leads (
    phone TEXT PRIMARY KEY,
    stage TEXT NOT NULL DEFAULT 'interesado',
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

CREATE TABLE IF NOT EXISTS agent_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    system_prompt_template TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '[]',
    fallback_responses TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inference_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    agent_id INTEGER,
    request_messages TEXT NOT NULL,
    response_raw TEXT,
    response_source TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    token_usage_prompt INTEGER DEFAULT 0,
    token_usage_completion INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_traces_phone ON inference_traces(phone, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_traces_correlation ON inference_traces(correlation_id);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    user_correlation_id TEXT,
    assistant_correlation_id TEXT,
    message_ids TEXT DEFAULT '[]',
    session_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_turns_phone_created ON turns(phone, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);

CREATE TABLE IF NOT EXISTS conversation_memory (
    phone TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    key_facts TEXT NOT NULL DEFAULT '[]',
    total_messages_summarized INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone) REFERENCES conversations(phone)
);

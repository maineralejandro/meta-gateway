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

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

ALTER TABLE messages ADD COLUMN correlation_id TEXT;
ALTER TABLE agent_decisions ADD COLUMN correlation_id TEXT;

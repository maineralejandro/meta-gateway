-- Migration: Baseline control table
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

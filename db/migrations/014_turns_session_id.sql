ALTER TABLE turns ADD COLUMN session_id TEXT REFERENCES sessions(id)

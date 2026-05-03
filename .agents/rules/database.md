# Database Rules

## Migrations

- **ALL schema changes MUST be migration files** — never edit a table via direct SQL or manual DB modification.
- Migrations live in `db/migrations/` with sequential numbering: `000_baseline.sql`, `001_initial_schema.sql`, `002_sessions.sql`, etc.
- The migrator (`db/migrator.py`) runs synchronously with `sqlite3` during startup, BEFORE the async event loop is available.
- Migrations are idempotent where possible: use `IF NOT EXISTS` for tables/indexes.
- **NEVER delete or rename an existing migration file** — it may already be applied in production.
- New migrations: increment the highest number by 1. Check existing files first.

## PRAGMA Configuration

These are set in `db/database.py:_get_conn()` and MUST remain:

```python
await self._conn.execute("PRAGMA journal_mode=WAL")
await self._conn.execute("PRAGMA foreign_keys=ON")
await self._conn.execute("PRAGMA busy_timeout=5000")
```

- **WAL mode**: enables concurrent reads while writing.
- **foreign_keys=ON**: enforces referential integrity at the SQLite level.
- **busy_timeout=5000**: retries locked DB for up to 5 seconds before raising.

## Critical: aiosqlite PRAGMA foreign_keys=OFF Does NOT Work

Setting `PRAGMA foreign_keys=OFF` via aiosqlite has **no effect** because:
1. aiosqlite runs on a background thread with an implicit transaction open.
2. SQLite PRAGMAs must be set outside any active transaction.
3. The setting silently fails — FK constraints remain enforced.

**Implication**: When deleting test data, you MUST respect FK order. There is no shortcut.

## Foreign Key-Safe Delete Order

When cleaning up the database (e.g., in test fixtures), delete in this exact order:

```
1. agent_decisions       (references messages.id)
2. escalation_events     (references conversations.phone)
3. messages              (references conversations.phone)
4. conversation_memory   (references conversations.phone)
5. UPDATE conversations SET current_session_id=NULL  (references sessions.id)
6. sessions              (references conversations.phone)
7. conversations         (referenced by many tables)
8. agents                (referenced by conversations.agent_id)
```

Skipping step 5 will cause FK violations when deleting sessions.

## Schema Overview

| Table | PK | Key FKs |
|-------|-----|---------|
| `agents` | `id` | — |
| `conversations` | `phone` | `agent_id → agents.id`, `current_session_id → sessions.id` |
| `messages` | `id` | `phone → conversations.phone`, `session_id → sessions.id` |
| `sessions` | `id` (UUID) | `phone → conversations.phone` |
| `escalation_events` | `id` | `phone → conversations.phone` |
| `conversation_memory` | `phone` | `phone → conversations.phone` |
| `agent_decisions` | `id` | `message_id → messages.id` |
| `schema_migrations` | `id` | — |

## Unique Indexes

- `idx_messages_meta_id` on `messages(meta_message_id)` — webhook dedup (migration 005)

## Connection Model

- Single shared `aiosqlite.Connection` via `db._get_conn()`.
- No connection pooling (SQLite is file-local).
- Transactions use `execute_transaction()` which does commit/rollback on the shared connection.
- The `Database` class is NOT thread-safe — it lives on the asyncio event loop thread only.

## Migrator Specifics

- `run_migrations()` uses **synchronous sqlite3** (not aiosqlite).
- It sets `PRAGMA foreign_keys=OFF` during migrations (this works because it's a fresh synchronous connection with no active transaction).
- ALTER TABLE statements are executed individually (not via `executescript()`) to catch and ignore "duplicate column" errors.
- After all migrations, it re-enables `PRAGMA foreign_keys=ON`.

# Testing Rules

## Test Runner

- **pytest** with `pytest.ini` setting `asyncio_mode = auto`
- No `@pytest.mark.asyncio` decorators needed — auto-detected for `async def test_*`
- Run: `python3 -m pytest tests/ -v`
- Single file: `python3 -m pytest tests/test_conversational.py -v`

## Test Structure

| File | Tests | Category |
|------|-------|----------|
| `test_conversational.py` | 23 | End-to-end message flow (mocked LLM) |
| `test_api.py` | 8 | FastAPI endpoints via ASGITransport |
| `test_database.py` | 3 | DB operations (transactions, fetch) |
| `test_final_integration.py` | 1 | Full conversation lifecycle |
| `test_inference.py` | 2 | Inference engine + fallback |
| `test_memory.py` | 10 | Memory context, order state, summarization |
| `test_migrator.py` | 3 | Migration system (fresh, idempotent, legacy) |
| `test_security.py` | 7 | HMAC, rate limiter, sanitize |
| `test_sentiment.py` | 10 | Sentiment analysis (heuristic) |
| `test_sessions.py` | 5 | Session lifecycle |

## conftest.py

Sets environment variables BEFORE any imports:
```python
os.environ.setdefault("DB_DIR", "/tmp/hermes_test")
os.environ.setdefault("DB_NAME", "test.db")
os.environ.setdefault("DB_PATH", "/tmp/hermes_test/test.db")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test-token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123456")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_verify")
os.environ.setdefault("LLM_API_KEY", "nvapi-REPLACE_ME")
os.environ.setdefault("DASHBOARD_TOKEN", "test_dashboard_token")
```

## Critical Patterns

### SKIP_STARTUP_VALIDATION

Tests using `ASGITransport` (which triggers FastAPI lifespan) MUST set:
```python
settings.SKIP_STARTUP_VALIDATION = True
```
This is required in: `test_api.py`, `test_conversational.py`, `test_final_integration.py`.

Without it, the lifespan raises `RuntimeError` because test env vars contain "REPLACE" or empty values.

### Patch Targets

When patching `process_inbound_message` for webhook tests, patch the **wrapper**:
```python
patch("routers.webhook._safe_process", ...)
```
NOT `core.hitl_router.process_inbound_message` — the webhook calls `_safe_process` which calls `hitl_router.process_inbound_message` via module attribute lookup.

### asyncio.create_task and asyncio.sleep(0)

Webhook handler uses `asyncio.create_task(_safe_process(phone, text))` — fire-and-forget.
After calling `receive_webhook()` in a test, you MUST yield to the event loop:
```python
response = await client.post("/webhook/whatsapp", json=payload)
await asyncio.sleep(0)  # Let create_task run
```
Without `sleep(0)`, the background task has not executed yet and mock assertions will fail.

### Patching asyncio.create_task for cleanup

Background tasks from `create_task` can leak between tests. To prevent this, patch `create_task` in conversational tests:
```python
with patch("core.hitl_router.asyncio.create_task", side_effect=lambda c: c.close()):
    ...
```
This prevents `maybe_summarize` tasks from running and interfering with subsequent tests.

### Unique meta_message_id

Each webhook message in tests MUST use a unique `meta_message_id`. The unique index on `messages(meta_message_id)` means reusing an ID within a test will trigger dedup and the message gets silently ignored.

BAD: using `meta_id_1` in step 1 and again in step 5.
GOOD: `meta_id_1`, `meta_id_2`, `meta_id_3`, etc.

### clean_db Fixture

For tests that need a clean database state, use the `clean_db` fixture which deletes all rows in FK-safe order (see `.agents/rules/database.md`).

## Test Data

- SQLite DB fixtures live in `tests/data/` (gitignored via `.gitignore`).
- They are created by tests on-demand, not committed to the repo.

## Dashboard Tests

- `dashboard/__tests__/` — Jest + React Testing Library
- Run: `cd dashboard && npm test`
- Only 3 component tests currently exist (AgentEditor, ChatPanel, ConversationList).

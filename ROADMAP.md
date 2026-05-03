# ROADMAP.md — Project Progress Tracker

## Completed

### Phase 1: Chronological Message Ordering
- Fixed `db/database.py:get_messages()` — added `desc: bool = False` parameter
- `build_context()` calls with `desc=True` + `reversed()` to get last N messages in chronological order
- **Status**: DONE

### Phase 2: Message Deduplication in Context
- `build_context()` accepts `current_message: str | None` to exclude the current inbound message
- `hitl_router.py` passes `current_message=text` to avoid double-injection
- **Status**: DONE

### Phase 3: Threshold Tuning
- `WINDOW_SIZE`: 8 → 16 (more context for LLM)
- `CONFIDENCE_THRESHOLD`: 0.7 → 0.5 (reduce false escalations)
- Heuristic neutral confidence: 0.7 → 0.8 (less likely to trigger low-confidence escalation)
- `should_escalate` rewritten with clear priority: LLM marker > negative sentiment > low confidence > keywords
- **Status**: DONE

### Phase 4: Order Tag System
- Created `core/order_state.py`: OrderState class, MENU_ITEMS, tag regex, `format_for_context()`, `parse_tags()`
- Integrated into `memory.py` (context injection), `hitl_router.py` (tag parsing), `sessions.py` (clear on timeout)
- Migration `004_order_tags_system_prompt.sql`: updated system prompt with ORDER_ADD/REMOVE/CLEAR instructions
- 7 new tests in `test_memory.py`
- 23 conversational tests in `test_conversational.py`
- **Status**: DONE

### Phase 5: Production Robustness
- **5.1** Per-phone `asyncio.Lock` in `hitl_router.py` — serializes concurrent messages from same phone
- **5.2** LLM retry/backoff/timeout in `inference.py` — 3 retries (1s/2s/4s backoff), 30s timeout, catches RateLimitError/APIConnectionError/APITimeoutError
- **5.3** `PRAGMA busy_timeout=5000` in `db/database.py:_get_conn()`
- **5.4** `_safe_process()` wrapper in `routers/webhook.py` + `_safe_summarize()` in `core/hitl_router.py` — catches exceptions, sends fallback to user, notifies dashboard
- **5.5** Webhook idempotency: migration 005 UNIQUE index on `meta_message_id`, check-before-insert dedup
- **5.6** Startup validation in `main.py` lifespan — checks required env vars, raises RuntimeError if missing/placeholder
- **Status**: DONE — 74/74 tests passing

### Agent Operation Files
- AGENTS.md, .agents/rules/{global,database,testing}.md, llms.txt, CONTEXT.md, ROADMAP.md, DESIGN.md
- **Status**: DONE

### Phase 6: Next-Level Production Hardening
- **6.1** Race condition fixes — `InferenceEngine` no shared mutable `agent_id`, `_get_phone_lock` uses `setdefault`, `Database._get_conn` double-checked locking
- **6.2** DB hardening — webhook dedup uses plain `INSERT` + catches `IntegrityError`; `execute_transaction` explicit BEGIN/COMMIT/ROLLBACK; pagination on conversations
- **6.3** Order persistence + DB_DIR — migration `006_orders_table.sql`; `OrderState` async methods with lazy DB persistence; `DB_DIR` default `./data`
- **6.4** Graceful shutdown — `core/task_tracker.py` tracks in-flight tasks; webhook uses `track_task()`; lifespan calls `wait_for_inflight()` with 10s timeout
- **6.5** Security — removed `debug_settings.py`; WS auth via first-message protocol; prompt injection defense with `<customer_message>` tags + anti-injection appendix
- **6.6** Architecture — `core/events.py` event bus; `db.insert_message()` centralized; all routers use `emit()`; 7 event types forwarded to WS
- **6.7** Observability — `core/metrics.py` with prometheus counters/histograms/gauges; `/metrics` endpoint; correlation IDs via `structlog.contextvars`; LLM token usage logging; `core/logging_config.py` with `merge_contextvars` processor
- **6.8** DX — `pyproject.toml` with ruff/mypy/pytest config; background cleanup task in `core/background.py`
- **6.9** Sentiment/Memory retry — `sentiment.py` and `memory.py` now have retry/backoff (2 retries, 1s/2s delays) matching `inference.py` pattern
- **6.10** Pydantic V2 migration — `class Config` → `model_config = SettingsConfigDict(...)` in `config.py`; `.dict()` → `.model_dump()` in `agents.py`; `LLM_MODEL` default fixed to `meta/llama-3.3-70b-instruct`
- **6.11** API rate limiting — `IPRateLimiter` in `core/security.py`; `APIRateLimitMiddleware` in `main.py` (60 req/min per IP); cleanup in background task
- **6.12** Test FK fix — `test_memory.py` clean_db fixture now nulls `current_session_id` before deleting sessions/conversations
- **Status**: DONE — 76/76 tests passing

## Current State

- **173 tests passing** (up from 76)
- **89% code coverage** (up from 78%)
- **0 ruff findings**, **0 mypy errors**
- 7 database migrations applied (000-006)
- LLM: `meta/llama-3.3-70b-instruct` via NVIDIA NIM
- 0 Pydantic deprecation warnings
- Production-ready features: dedup, retry/backoff on all LLM calls, rate limiting (webhook + API), HMAC validation, startup checks, prometheus metrics, correlation IDs, graceful shutdown, event bus, order persistence
- 100% coverage modules: `core/events.py`, `core/meta_client.py`, `core/sentiment.py`, `core/task_tracker.py`, `routers/messages.py`

## Potential Next Steps (not committed)

| Priority | Feature | Description |
|----------|---------|-------------|
| High | E2E test with real LLM | Integration test against staging NVIDIA NIM (currently all LLM calls mocked) |
| Medium | Coverage > 90% | Remaining gaps: `core/memory.py` (83%), `core/metrics.py` (76%), `main.py` lifespan (77%), `routers/conversations.py` (71%), `routers/ws.py` websocket endpoint (65%) |
| Medium | Multi-tenant | Tenant isolation per food truck (RLS-like via phone prefix or tenant_id) |
| Medium | Payment integration | Generate payment links (MercadoPago/Flow) on order confirmation |
| Low | Dashboard improvements | Message search, export conversations, sentiment timeline chart |
| Low | Voice message transcription | Whisper API for audio message handling |
| Low | Multi-agent routing | Route to different agent personas based on customer segment |

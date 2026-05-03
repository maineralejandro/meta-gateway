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

### Phase 7: Security Audit Fixes
- **7.1** Webhook signature mismatch log no longer leaks `expected`/`provided` hash values — `core/security.py:44` logs only `"webhook_signature_mismatch"`
- **7.2** CORS `allow_credentials=False` when `CORS_ORIGINS` contains `*` — `main.py`; `True` only for explicit origins
- **7.3** New tests: `test_signature_mismatch_no_hash_leak`, `test_cors_no_credentials_with_wildcard_origin`
- **Status**: DONE

### Phase 8: Error Handling Audit
- **8.1** `core/order_state.py` — 3 `except Exception: pass` → proper logging with `logger.error`
- **8.2** `routers/conversations.py:93` — HTTP 200 for not-found → `JSONResponse(status_code=404, ...)`
- **8.3** Expanded `tests/test_order_state.py` to 20+ tests including resurrection and persist-failure scenarios
- **Status**: DONE

### Phase 9: Sentiment Bug Fix
- **9.1** `core/sentiment.py` — positive words checked BEFORE negative heuristics; removed duplicate `"excelente"`
- **9.2** 6 new heuristic tests for positive/negative priority
- **Status**: DONE

### Phase 10: LLM Client Consolidation
- **10.1** Created `core/llm_client.py` — shared `LLMClient` class with lazy `AsyncOpenAI` init, availability check, configurable retry/backoff/timeout, `chat_completion()` with `raise last_err from None`
- **10.2** Rewrote `core/inference.py`, `core/memory.py`, `core/sentiment.py` — all use `self._llm = LLMClient(...)`
- **10.3** 10 tests in `tests/test_llm_client.py`; updated mocks in all test files
- **Status**: DONE

### Phase 11: Order Persistence Robustness
- **11.1** Fixed `clear()` resurrection bug — `clear()` now does `db.delete_order()` FIRST; on DB failure, in-memory state preserved
- **11.2** Fixed `_persist` failure leaving stale cache — on exception, invalidates in-memory cache (`pop` + `discard`)
- **11.3** Added `db.escalate_conversation()` and `db.update_conversation_sentiment()` — replaces raw SQL in `hitl_router.py`
- **11.4** Rewrote `core/hitl_router.py` cleanly — uses new DB methods
- **11.5** New tests: `test_clear_prevents_resurrection`, `test_persist_failure_invalidates_cache`
- **Status**: DONE

### Phase 12: Menu Configuration
- **12.1** Created `config/menu.json` — external JSON config for menu items
- **12.2** `core/order_state.py` — `MENU_ITEMS` loaded from JSON file via `_load_menu_from_file()` with `DEFAULT_MENU_ITEMS` fallback; added `get_menu()`, `reload_menu_from_db()` methods; instance uses `self._menu`
- **12.3** Migration `007_menu_items_table.sql` — `menu_items` table with key, name, price, category, is_available, sort_order + seed data
- **12.4** `db/database.py` — added `load_menu_items()`, `upsert_menu_item()`, `update_conversation_state()`, `reset_conversation_session()`, `set_conversation_agent()`
- **12.5** 8 new menu config tests + 6 new DB method tests
- **Status**: DONE

### Phase 13: Cleanup
- **13.1** Removed `python-dotenv` from `pyproject.toml` and `requirements.txt` (pydantic-settings handles `.env` natively)
- **13.2** `routers/conversations.py` — replaced raw SQL with `db.set_conversation_agent()`, `db.reset_conversation_session()`
- **13.3** `core/sessions.py` — replaced raw SQL with `db.update_conversation_state()`
- **13.4** Updated `db/schema.sql` with `menu_items` table
- **13.5** Updated migrator test for 7 migrations (001-007)
- **Status**: DONE

### Phase 14: Silent Error Audit
- **14.1** `core/inference.py:124` — malformed `fallback_responses` JSON now logs `logger.warning("fallback_json_parse_error", ...)`
- **14.2** `core/metrics.py:84,97` — metric refresh failures now log `logger.warning("metrics_refresh_failed", ...)`
- **14.3** `main.py:195` — health check DB failure now logs `logger.warning("health_check_db_failed", ...)`
- **14.4** `routers/ws.py:32,40` — WS send failures now log `logger.debug("ws_send_all_failed"/"ws_send_one_failed")`
- **14.5** No remaining `except Exception: pass` in source code — all have logging
- **Status**: DONE

## Current State

- **228 tests passing**, 3 skipped (E2E)
- **0 ruff findings**, **0 mypy errors** (27 source files)
- 8 database migrations (000-007)
- LLM: `meta/llama-3.3-70b-instruct` via NVIDIA NIM
- 0 Pydantic deprecation warnings
- All `except Exception` blocks have proper logging — zero silent swallowing
- Menu: `config/menu.json` + DB `menu_items` table + `OrderState.reload_menu_from_db()`
- Raw SQL eliminated from `routers/` and `core/` — all through `db/database.py` methods
- `python-dotenv` removed (pydantic-settings handles `.env` natively)
- Production-ready features: dedup, retry/backoff on all LLM calls, rate limiting (webhook + API), HMAC validation, startup checks, prometheus metrics, correlation IDs, graceful shutdown, event bus, order persistence, menu config

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

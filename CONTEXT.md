# CONTEXT.md — Long-Term Project Memory

## Business Domain

Hermes is a WhatsApp bot for a Chilean Food Truck. Customers send messages to order food (completos, chorrillanas, papas fritas, bebidas). The bot handles ordering, pricing, and delivery questions. When a customer is upset, wants to cancel, or the bot is unsure, it escalates to a human operator who uses the Next.js dashboard.

## Architecture

### Message Flow (happy path)

1. Customer sends WhatsApp message
2. Meta Cloud API delivers webhook to `POST /webhook/whatsapp`
3. `verify_meta_signature()` validates HMAC-SHA256
4. Dedup check: `SELECT id FROM messages WHERE meta_message_id=?`
5. Rate limit check: 30 messages/minute per phone
6. Session resolution: get_or_create with 4h timeout
7. If `state=BOT_ACTIVE`: `asyncio.create_task(_safe_process(phone, text))`
8. Inside `_process_inbound_message_inner` (protected by per-phone asyncio.Lock):
   a. Sentiment analysis (LLM or heuristic fallback)
   b. Context build: memory summary + order state + last 16 messages
   c. LLM inference (3 retries, 1s/2s/4s backoff, 30s timeout)
   d. Escalation decision: keyword, negative sentiment, low confidence, or LLM marker
   e. If escalate: update state, send handoff message, notify dashboard
   f. If not: parse `[ORDER_ADD/REMOVE/CLEAR]` tags, sanitize, send via Meta API
   g. Fire-and-forget: `maybe_summarize()` via `_safe_summarize()`

### Escalation Logic

A conversation escalates when ANY of:
- LLM response contains `ESCALATE_TO_HUMAN` marker
- Sentiment is negative AND score < 0.3
- Confidence < 0.4 (without LLM escalation)
- Text contains escalation keywords: cancelar, molesto, reclamo, queja, devolución

On escalation: state → PENDING_APPROVAL, human reviews via dashboard, can transition to HUMAN_ONLY.

### Order Tag System

LLM emits invisible tags that the backend parses to maintain order state:
- `[ORDER_ADD:item_key:quantity]` — add or increment item
- `[ORDER_REMOVE:item_key:quantity]` — remove or decrement item
- `[ORDER_REMOVE:item_key]` — remove item entirely
- `[ORDER_CLEAR]` — reset entire order

Tags are stripped from the response before sending to the customer.
Order state is DB-backed with in-memory cache (`OrderState` class), keyed by phone number.
`_ensure_loaded` lazy-loads from DB on first access per phone; `_persist` writes after each mutation.
`clear()` does DB delete first, then in-memory cleanup — prevents resurrection on reload.
`_persist` failure invalidates in-memory cache so next access reloads from DB.
Order state is injected into LLM context as a system message.
Order state is cleared on session timeout (4h inactivity).

### Menu Configuration

Menu items are loaded from `config/menu.json` at module import time via `_load_menu_from_file()`.
If the JSON file is missing or invalid, `DEFAULT_MENU_ITEMS` (hardcoded dict) is used as fallback.
A `menu_items` DB table (migration 007) supports runtime menu management via `reload_menu_from_db()`.
The `OrderState` instance uses `self._menu` — initially loaded from JSON, overridable from DB.

### Memory / Summarization

- Last 16 messages sent verbatim as context
- Older messages summarized every 15 new messages via a separate LLM call
- Summary stored in `conversation_memory` table
- Key facts (name, address, preferences) extracted as JSON array

## Key Decisions & Lessons Learned

### aiosqlite PRAGMA foreign_keys=OFF Does NOT Work

Setting `PRAGMA foreign_keys=OFF` via aiosqlite has no effect. aiosqlite runs on a background thread with an implicit transaction. SQLite requires PRAGMAs be set outside any transaction. The setting silently fails — FKs remain enforced.

**Workaround**: Delete test data in FK-safe order. Never rely on disabling FKs in runtime code.

### asyncio.create_task is Fire-and-Forget

`asyncio.create_task()` starts a background coroutine that runs on the next event loop tick. In tests, you need `await asyncio.sleep(0)` after the webhook call to let these tasks execute. Between tests, leaked tasks can cause interference — patch `create_task` with `side_effect=lambda c: c.close()` to suppress them.

### _safe_process Must Use Module Attribute Lookup

The `_safe_process` wrapper in `routers/webhook.py` calls `hitl_router.process_inbound_message` — not a captured import. This is intentional: tests patch `routers.webhook._safe_process`, and the module-level function resolves `hitl_router` at call time.

### Startup Validation

`main.py` lifespan validates that required env vars are set and don't contain "REPLACE". Tests set `settings.SKIP_STARTUP_VALIDATION = True` to bypass this.

### Webhook Dedup

Migration 005 adds a UNIQUE index on `messages(meta_message_id)`. The webhook handler checks for existing rows before inserting. Duplicate webhooks return `{"status": "duplicate"}` instead of raising IntegrityError.

### Per-Phone Lock

`hitl_router.py` maintains `_phone_locks: dict[str, asyncio.Lock]`. Two concurrent messages from the same phone are serialized, preventing interleaving between sentiment analysis and order state mutation.

### Webhook Signature Verification

`core/security.py` logs `"webhook_signature_mismatch"` on HMAC failure — never logs the expected/provided hash values to avoid leaking partial signature data.

### CORS Credentials

`main.py` sets `allow_credentials=False` when `CORS_ORIGINS` contains `*` (wildcard). Only enables `allow_credentials=True` for explicit origin lists. This prevents browser CORS policy violations.

### LLM Client Consolidation

`core/llm_client.py` provides a shared `LLMClient` class with lazy `AsyncOpenAI` init, availability check, configurable retry/backoff/timeout, and `chat_completion()` with `raise last_err from None`. Each module (`inference.py`, `memory.py`, `sentiment.py`) creates its own `LLMClient` instance with appropriate params. `raise last_err from None` avoids circular tracebacks.

### Order State Persistence

- DB-backed with in-memory cache (not in-memory primary)
- `clear()` does DB delete FIRST → on failure, in-memory preserved (returns early) → on success, pops from `_orders`/`_loaded_phones`
- `_persist()` failure invalidates in-memory cache (`pop` + `discard`) so next `_ensure_loaded` reloads from DB

### Edit Tool Indentation Pitfall

The edit tool can lose 4 spaces of indentation on multi-line replacements. This has caused syntax errors in:
- `core/memory.py`: `raw_content` check dedented out of outer `try` block
- `core/order_state.py`: `parse_tags` body dedented out of method
- `core/inference.py`: for loop + try block dedented out of outer `try` block
- `routers/ws.py`: `except Exception` dedented to wrong indent level
- `test_inference.py`: test function body dedented

**Mitigation**: After multi-line edits, verify with `python3 -c "import ast; ast.parse(open('file').read())"` or check raw byte indentation. For large blocks, prefer writing the entire file.

## Known Limitations

- SQLite single-writer limitation — WAL mode helps but heavy concurrent writes may still contend
- No multi-tenant isolation — single food truck deployment
- No authentication on webhook GET (verify token is static, no HMAC on GET)

## Quality Gates (Current Status)

- **Ruff**: 0 findings
- **Mypy**: 0 errors (27 source files checked)
- **Tests**: 228 passed, 3 skipped (E2E), 0 failures
- **Database migrations**: 8 (000-007)
- **Menu config**: `config/menu.json` + DB `menu_items` table
- **No `except Exception: pass`** remaining in source — all have logging

## Type Annotation Strategy

- All source files fully annotated with `-> None`, `-> str`, `-> dict[str, Any]`, etc.
- `Any` used for complex callable/dict types and external library return types
- `tuple[Any, ...]` for database parameter tuples
- `dict[str, Any]` for generic dicts (sentiment results, decision data, WS messages)
- Walrus operator `if (c := row_to_*(r)) is not None` for list comprehension type narrowing
- `assert cursor.lastrowid is not None` before returning from insert methods
- `str()` cast on `fallbacks.get()` returns to avoid `Returning Any from function declared to return "str"`
- `ChatCompletion` type annotation on LLM response variable to avoid `str`/`ChatCompletion` union issues
- `# type: ignore[arg-type]` for OpenAI `messages` param (dict vs strict union type)

# AGENTS.md — Hermes WhatsApp HITL Gateway

## Vision

Hermes is a WhatsApp Human-in-the-Loop gateway for a Chilean Food Truck. It receives customer messages via Meta Cloud API webhook, processes them through an LLM agent (NVIDIA NIM / Llama 3.3 70B), tracks orders via tag-based state machine, and escalates to human operators when sentiment/confidence thresholds are breached. A Next.js dashboard provides real-time conversation monitoring and agent configuration.

## Tech Stack

### Backend (Python 3.12+)
- **FastAPI 0.115.0+** — async API framework with lifespan events
- **aiosqlite 0.22.1** — async SQLite wrapper (single shared connection)
- **openai >=1.0.0** — OpenAI-compatible client for NVIDIA NIM
- **httpx 0.28.1** — async HTTP client for Meta API calls
- **structlog 24.1.0** — structured JSON logging
- **pydantic-settings 2.14.0** — .env-based configuration with validation
- **uvicorn 0.24.0** — ASGI server with --reload for dev
- **websockets 16.0** — WebSocket support for dashboard

### Frontend (Node 18+)
- **Next.js 14** — React dashboard with dark theme
- **React 18 + Tailwind CSS 3.4** — UI components
- **lucide-react** — icon library

### Infrastructure
- **SQLite** with WAL mode, busy_timeout=5000ms, foreign_keys=ON
- **ngrok** for tunneling Meta webhook in dev
- **tmux** session manager (see `start_all.sh`)

## Commands

### Run tests
```bash
python3 -m pytest tests/ -v
```

### Run linting
```bash
python3 -m ruff check .
```

### Run type checking
```bash
python3 -m mypy core/ db/ routers/ main.py
```

### Run backend
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

### Run dashboard
```bash
cd dashboard && npm run dev
```

### Start everything (dev)
```bash
bash start_all.sh
```

### Install Python deps
```bash
pip install -r requirements.txt
```

### Install dashboard deps
```bash
cd dashboard && npm install
```

## Boundaries — What the Agent MUST NOT Do

1. **NEVER commit `.env`** — it contains real API keys and tokens
2. **NEVER modify `.db` files directly** — all schema changes must be migration files
3. **NEVER disable `PRAGMA foreign_keys=ON` in runtime code** — it does not work via aiosqlite anyway
4. **NEVER delete or rename existing migration files** — they are versioned and already applied
5. **NEVER use `print()`** — use `structlog.get_logger()` for all logging
6. **NEVER use `cd <dir> && <cmd>` in Bash tool** — use the `workdir` parameter instead
7. **NEVER push to remote** without explicit user request
8. **NEVER force-push to main/master** — warn the user if requested
9. **NEVER add comments** to code unless explicitly asked
10. **NEVER add emojis** to code or responses unless explicitly asked

## Boundaries — What the Agent CAN Do

1. Edit Python source, tests, and migration files
2. Create new migration files (sequential numbering)
3. Add/modify dashboard components
4. Run tests, linting, and type checking
5. Create new files when required for a feature
6. Edit documentation files (AGENTS.md, CONTEXT.md, etc.)
7. Stage and commit changes when explicitly asked

## Architecture Overview

```
WhatsApp User
     │
     ▼
Meta Cloud API ──webhook──► routers/webhook.py
     │                          │
     │                     dedup (meta_message_id)
     │                     rate_limiter
     │                     session_manager
     │                          │
     │              ┌───────────┴───────────┐
     │              ▼                       ▼
     │    state=HUMAN_ONLY?        state=BOT_ACTIVE?
     │    (pending_human)                  │
     │                           core/hitl_router.py
     │                          (per-phone asyncio.Lock)
     │                              │
     │                   ┌──────────┼──────────┐
     │                   ▼          ▼          ▼
     │            sentiment    inference   order_state
     │            .py          .py          .py
     │                   │          │          │
     │                   └──────────┼──────────┘
     │                              ▼
     │                    should_escalate?
     │                   ╱              ╲
     │               YES                 NO
     │                │                   │
     │         PENDING_APPROVAL    parse_tags + sanitize
     │         + notify dashboard   + send via Meta API
     │                              + maybe_summarize
     │
     ▼
Next.js Dashboard (WebSocket real-time)
```

## Key Singletons

| Module | Singleton | Purpose |
|--------|-----------|---------|
| `db/database.py` | `db` | Async SQLite connection |
| `core/hitl_router.py` | `hitl_router` | Message processing orchestrator |
| `core/inference.py` | `inference_engine` | LLM client with retry/backoff |
| `core/memory.py` | `memory_manager` | Context window + summarization |
| `core/sentiment.py` | `sentiment_analyzer` | Sentiment + heuristic fallback |
| `core/order_state.py` | `order_state` | In-memory order tracking per phone |
| `core/sessions.py` | `session_manager` | Session lifecycle with 4h timeout |
| `core/meta_client.py` | `meta_client` | WhatsApp API HTTP client |
| `core/security.py` | `rate_limiter` | Per-phone rate limiting (30/min) |
| `routers/ws.py` | `manager` | WebSocket connection manager |

## Configuration

All config via `core/config.py` (Pydantic Settings) reading from `.env`. Key variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `WHATSAPP_ACCESS_TOKEN` | Meta API auth | (required) |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta phone ID | (required) |
| `META_APP_SECRET` | Webhook HMAC verification | (required) |
| `LLM_API_KEY` | NVIDIA NIM API key | (required) |
| `LLM_MODEL` | Model ID | `meta/llama-3.1-70b-instruct` |
| `LLM_BASE_URL` | NIM endpoint | `https://integrate.api.nvidia.com/v1` |
| `DB_DIR` | SQLite directory | `/tmp/hermes` |
| `DASHBOARD_TOKEN` | Auth for API/WS | (required) |
| `SKIP_STARTUP_VALIDATION` | Bypass credential checks | `false` |

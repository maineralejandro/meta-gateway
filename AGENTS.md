# AGENTS.md — Hermes WhatsApp HITL Gateway

## Vision

Hermes is a WhatsApp Human-in-the-Loop gateway for any retail business. It receives customer messages via Meta Cloud API webhook, processes them through an LLM agent (NVIDIA NIM / Llama 3.3 70B), tracks carts via tool-based state machine, and escalates to human operators when sentiment/confidence thresholds are breached. A Next.js dashboard provides real-time conversation monitoring and agent configuration.

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
│ sentiment inference cart_state
│ .py .py .py
     │                   │          │          │
     │                   └──────────┼──────────┘
     │                              ▼
     │                    should_escalate?
     │                   ╱              ╲
     │               YES                 NO
     │                │                   │
│ PENDING_APPROVAL execute_tool_calls + sanitize
│ + notify dashboard + send via Meta API
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
| `core/cart_state.py` | `cart_state` | In-memory cart tracking per phone |
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
| `LLM_MODEL` | Model ID | `meta/llama-3.3-70b-instruct` |
| `LLM_BASE_URL` | NIM endpoint | `https://integrate.api.nvidia.com/v1` |
| `DATABASE_URL` | PostgreSQL connection | `postgresql://postgres:postgres@localhost:54322/postgres` |
| `DASHBOARD_TOKEN` | Auth for API/WS | (required) |
| `SKIP_STARTUP_VALIDATION` | Bypass credential checks | `false` |

### Meta API Token — Temporary vs System User

**Temporary Access Tokens** (generated from Meta App Dashboard → API Setup) expire in ~1-24 hours. The app logs `meta_token_expired` with `error_subcode=463` when they expire. The startup `check_token_health()` call warns if the token expires within 60 minutes.

**System User Tokens** do NOT expire. To create one:
1. Go to [Meta Business Manager](https://business.facebook.com/settings/system-users)
2. Business Settings → Users → System Users → Add
3. Assign the WhatsApp Business Management and Messaging permissions
4. Generate token → copy to `.env` as `WHATSAPP_ACCESS_TOKEN`

Token resolution priority in `core/meta_client.py`: `dotenv_values(.env)` → `os.environ` → `settings.WHATSAPP_ACCESS_TOKEN`. The `.env` file is read fresh on every request via `dotenv_values()`, which works with Docker bind mounts (the container sees the updated file on the host). `os.environ` is the fallback (used by `start_all.ps1` or Docker `env_file`), and `settings` is the last resort. This means: updating `.env` on the host takes effect immediately inside the Docker container without restart, because `dotenv_values()` reads the bind-mounted file directly.

## Technical Debt

### i18n — Hardcoded Spanish in LLM-facing strings
All LLM-facing strings (system prompts, tool descriptions, escalate messages) are hardcoded in Spanish. This is intentional for the current Chile deployment but blocks multi-locale support. Key locations:
- `db/migrations/001_initial_schema.sql` — system prompt content
- `db/migrations/004_order_tags_system_prompt.sql` — agent prompt
- `db/migrations/010_agent_templates.sql` — greeting template
- `core/inference.py` — tool discipline / escalate description
- `core/memory.py` — summarization context
- `core/capabilities/cart.py` — tool descriptions and response messages

Resolution path: extract all user-facing strings to a locale file (e.g. `config/locales/es.json`), load at runtime based on agent config. No immediate action required until multi-locale is needed.

### Migration SQL — no semicolons in comments
The migrator splits on `;` via dumb string split — it does not parse SQL comments. Any `;` inside `--` comments will be treated as a statement separator and cause syntax errors. All migration files must avoid `;` in comments.

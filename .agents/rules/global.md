# Global Rules

## Language

- **Code**: English — variable names, function names, class names, module names, comments (when asked)
- **UI and customer-facing text**: Spanish (Chilean dialect) — "completo", "papas fritas", "bebida", etc.
- **Log messages**: English snake_case keys — `order_item_added`, `inference_error`, `webhook_verified`
- **Error messages in logs**: English
- **User-facing error/fallback messages**: Spanish — "Lo siento, el sistema no está disponible en este momento."

## Architecture Patterns

### Composition over inheritance
- Core modules use standalone classes with a module-level singleton: `hitl_router = HITLRouter()`
- No class hierarchies. Modules communicate via imports of singletons.
- Example: `hitl_router.py` imports `inference_engine`, `sentiment_analyzer`, `order_state`, `memory_manager` — not inherited.

### Singletons
- Every core module exports a singleton instance at module bottom:
  ```python
  class Foo:
      ...
  foo = Foo()
  ```
- Tests patch these singletons, not the class constructor.

### Async-first
- All I/O (DB, HTTP, LLM) is async (`async def`).
- No `asyncio.run()` inside the app — let the event loop handle it.
- Fire-and-forget tasks use `asyncio.create_task()` wrapped in a safe handler (`_safe_process`, `_safe_summarize`).

### Structured logging
- Always `logger = structlog.get_logger()` at module top.
- Never `print()`.
- Log with key-value pairs: `logger.info("event_name", phone=phone, key=value)`

## Code Style

- **Type hints** required on all public function signatures.
- **No comments** unless explicitly requested.
- **No emojis** unless explicitly requested.
- **Trailing commas** in multi-line collections.
- **f-strings** for formatting (not `%` or `.format()`).
- **Single quotes** not enforced — follow existing file convention (project uses double quotes).
- **Max line length**: follow existing code (no strict limit, but keep readable).

## Imports

- Standard library first, then third-party, then local.
- Use explicit imports, not wildcard: `from core.config import settings` (not `from core.config import *`).
- Avoid circular imports: routers import from core, core never imports from routers.

## Error Handling

- Top-level exception handlers in orchestrators (`_safe_process`, `_safe_summarize`, `_process_inbound_message_inner`).
- Never let exceptions escape from `asyncio.create_task()` — always wrap.
- Log the error, then degrade gracefully (fallback response, notify dashboard).
- Never silently swallow exceptions without logging.

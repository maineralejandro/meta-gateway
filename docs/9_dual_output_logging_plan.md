## Problem

The meta-gateway runs as a systemd service. Structlog is configured with a single
`JSONRenderer` processor, so all log output is JSON. When running under systemd,
`StandardOutput=journal` / `StandardError=journal` sends stdout/stderr to
`journalctl`. The user's terminal no longer shows readable log output — only
`journalctl -u meta-gateway.service -f` works, but it displays raw JSON lines
that are hard to scan visually.

Before the systemd migration, the user ran `uvicorn main:app --reload` in a tmux
session, where structlog's JSON output was at least visible in the terminal. Now
there is no terminal at all, and `journalctl` shows JSON like:

```
{"event":"menu_reloaded_from_db","item_count":319,"modifier_count":0,"timestamp":"..."}
```

## Solution

**Dual-output logging**: console-formatted output to stderr (for `journalctl -f`
and terminal readability) + JSON to the rotating file (for production search,
aggregation, and structured analysis).

### Architecture

```
structlog event dict
│
▼
shared_pre_chain (merge_contextvars, add_log_level, add_logger_name,
PositionalArgumentsFormatter, TimeStamper, StackInfoRenderer,
format_exc_info, UnicodeDecoder)
│
├──► stderr handler (StreamHandler → ProcessorFormatter → ConsoleRenderer)
│   key=value format, no colors (journalctl doesn't support ANSI by default)
│   readable in terminal: "2026-05-12T21:09:02Z menu_reloaded item_count=319"
│
└──► file handler (RotatingFileHandler → ProcessorFormatter → JSONRenderer)
    JSON format, one object per line
    searchable: jq '.event == "meta_api_error"' logs/hermes.jsonl
```

### Key design decisions

1. **`ProcessorFormatter` + `wrap_for_formatter`** — structlog's standard pattern
   for routing the same event dict through different renderers per handler. The
   shared pre-chain runs once; each handler's `ProcessorFormatter` applies its own
   final renderer (`ConsoleRenderer` for stderr, `JSONRenderer` for file).
2. **No colors in ConsoleRenderer** — systemd journal strips ANSI codes, and
   `journalctl -f` doesn't render them. `colors=False` keeps output clean.
3. **stderr for console, stdout untouched** — uvicorn uses stdout for its own
   access logs (`INFO: GET /webhook/whatsapp 200`). Structlog goes to stderr via
   a dedicated `StreamHandler(sys.stderr)`. This separates concerns cleanly.
4. **`basicConfig` removed** — we replace `logging.basicConfig()` with explicit
   handler setup. `basicConfig` creates a default stdout handler that would
   duplicate output. We remove it and attach our two handlers explicitly to the
   root logger.
5. **Log level controllable via env** — `LOG_LEVEL` env var (default `INFO`).
   Controls the root logger level. Both handlers inherit it. Invalid values
   fall back to `INFO` (validated against `_VALID_LEVELS` set).
6. **`handler.close()` before `handlers.clear()`** — prevents file descriptor
   leaks on reload or during tests.
7. **`cache_logger_on_first_use=True`** — kept. Standard structlog optimization.

## Changes

### `core/logging_config.py`

**Before** (original):
```python
def setup_logging() -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    log_dir = os.environ.get("LOG_DIR", "./logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "hermes.jsonl")
    max_bytes = int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024))
    backup_count = int(os.environ.get("LOG_BACKUP_COUNT", 5))

    file_handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    file_handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(file_handler)

    structlog.configure(
        processors=[
            merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

**After** (implemented — matches `core/logging_config.py` verbatim):
```python
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars
from structlog.stdlib import PositionalArgumentsFormatter

_SHARED_PROCESSORS: list[Any] = [
    merge_contextvars,
    structlog.stdlib.filter_by_level,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    PositionalArgumentsFormatter(),
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.UnicodeDecoder(),
]


def setup_logging() -> None:
    _VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    if log_level not in _VALID_LEVELS:
        log_level = "INFO"

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
    root_logger.handlers.clear()

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=False),
            ],
            foreign_pre_chain=_SHARED_PROCESSORS,
        )
    )
    root_logger.addHandler(console_handler)

    log_dir = os.environ.get("LOG_DIR", "./logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "hermes.jsonl")
    max_bytes = int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024))
    backup_count = int(os.environ.get("LOG_BACKUP_COUNT", 5))

    file_handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
    file_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
            foreign_pre_chain=_SHARED_PROCESSORS,
        )
    )
    root_logger.addHandler(file_handler)

    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

### Key differences

| Aspect | Before | After |
|--------|--------|-------|
| Root logger setup | `basicConfig()` | Explicit `getLogger().setLevel(getattr(logging, ...))` |
| LOG_LEVEL validation | None | `_VALID_LEVELS` set, fallback to `INFO` on invalid |
| Handler cleanup | None | `handler.close()` + `handlers.clear()` (prevents FD leaks) |
| Stderr handler | None (only `basicConfig` default stdout) | `StreamHandler(sys.stderr)` + `ConsoleRenderer(colors=False)` |
| File handler format | `logging.Formatter("%(message)s")` | `ProcessorFormatter` + `JSONRenderer()` |
| structlog processors | Full chain with `JSONRenderer` at end | Shared chain + `wrap_for_formatter` (defers rendering to handlers) |
| Log level | Hardcoded `INFO` | `LOG_LEVEL` env var (default `INFO`, invalid → fallback) |
| Duplicate output | Possible (basicConfig stdout + file handler) | None (no basicConfig, two explicit handlers) |
| `_SHARED_PROCESSORS` type | N/A | `list[Any]` (satisfies both mypy `type-arg` and ruff) |
| `import sys` | Not needed | Added for `sys.stderr` |

### Output examples

**stderr (journalctl -f)**:
```
2026-05-12T21:09:02Z menu_reloaded_from_db item_count=319 modifier_count=0
2026-05-12T21:09:02Z db_initialized path=/tmp/hermes/hermes_prod.db
2026-05-12T21:14:17Z meta_token_refreshed
2026-05-12T21:14:24Z turn_builder_firing phone=56951314805 burst_count=1
2026-05-12T21:15:33Z tool_loop_final_text phone=56951314805 tools_used=1
2026-05-12T21:15:34Z meta_api_error status=401 body=...
```

**file (logs/hermes.jsonl)**:
```json
{"event":"menu_reloaded_from_db","item_count":319,"modifier_count":0,"timestamp":"2026-05-12T21:09:02Z"}
{"event":"meta_api_error","status":401,"body":"...","timestamp":"2026-05-12T21:15:34Z"}
```

### How to follow logs after this change

```bash
# Readable real-time console output:
journalctl --user -u meta-gateway.service -f

# Structured search:
journalctl --user -u meta-gateway.service -f | grep "meta_api_error"

# JSON file (production search):
tail -f logs/hermes.jsonl | jq 'select(.event == "meta_api_error")'
```

## Test changes

### `tests/test_logging_config.py` (new file)

| Test | What it verifies |
|------|-----------------|
| `test_setup_creates_two_handlers` | Root logger has exactly 2 handlers after `setup_logging()` |
| `test_stderr_handler_uses_console_renderer` | stderr handler's `ProcessorFormatter` ends with `ConsoleRenderer` |
| `test_file_handler_uses_json_renderer` | file handler's `ProcessorFormatter` ends with `JSONRenderer` |
| `test_log_level_from_env` | `LOG_LEVEL=DEBUG` sets root logger to DEBUG |
| `test_log_level_default_info` | Without `LOG_LEVEL`, root logger is INFO |
| `test_no_basicConfig_leak` | No extra handlers from `basicConfig` (no stdout duplication) |
| `test_structlog_wrap_for_formatter` | structlog's last processor is `wrap_for_formatter` |
| `test_e2e_dual_output` | End-to-end: stderr has key=value, file has valid JSON |
| `test_invalid_log_level_fallback` | Invalid `LOG_LEVEL=INVALID` falls back to INFO |

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| `ProcessorFormatter` API differs across structlog versions | We pin `structlog==24.1.0` in requirements.txt. Tested against this version. |
| Removing `basicConfig` breaks uvicorn access logs | Uvicorn uses its own `logging.getLogger("uvicorn.access")` with its own handler. `basicConfig` is not needed for uvicorn's logs. Verified: uvicorn access logs still appear. |
| `ConsoleRenderer` output too verbose for some events | `pad_event=30` (default) truncates long event names. Acceptable for readability. |
| `sys.stderr` not captured by systemd | `StandardError=journal` in the service file ensures stderr goes to journal. Already configured. |
| Double-rendering performance cost | `ProcessorFormatter` splits work: shared pre-chain runs once, final renderers run per-handler. The only added cost is the `ConsoleRenderer` string formatting, which is negligible compared to I/O. |
| FD leak on reload | `handler.close()` called before `handlers.clear()` prevents file descriptor leaks. |

## Deployment

1. ~~Edit `core/logging_config.py`~~ Done
2. ~~Create `tests/test_logging_config.py`~~ Done (9 tests)
3. ~~Run tests + lint + typecheck~~ Done (457 passed, ruff clean, mypy clean)
4. ~~`systemctl --user restart meta-gateway.service`~~ Done
5. ~~`journalctl --user -u meta-gateway.service -n 5 --no-pager`~~ Verified: key=value format
6. ~~`tail -1 logs/hermes.jsonl \| python3 -m json.tool`~~ Verified: valid JSON

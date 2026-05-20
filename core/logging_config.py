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
    # Validate LOG_LEVEL to prevent crashes on invalid values
    _VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    if log_level not in _VALID_LEVELS:
        log_level = "INFO"  # Default fallback

    # Get root logger and close any existing handlers to prevent file descriptor leaks
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
    root_logger.handlers.clear()

    # Set log level from env var or default to INFO
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Handler 1: stderr → ConsoleRenderer (readable key=value for journalctl -f)
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

    # Handler 2: file → JSONRenderer (structured JSONL for production search)
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

    logging.getLogger("httpx").setLevel(logging.WARNING)

    # Configure structlog
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

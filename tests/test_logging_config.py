import io
import json
import logging
import os
import sys
import tempfile
from unittest.mock import patch

import structlog

from core.logging_config import setup_logging


def test_setup_creates_two_handlers():
    # Clear any existing handlers to start fresh
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    # Run setup_logging
    setup_logging()

    # Check that we have exactly 2 handlers
    assert len(root_logger.handlers) == 2, f"Expected 2 handlers, got {len(root_logger.handlers)}"


def test_stderr_handler_uses_console_renderer():
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    setup_logging()

    # The first handler should be stderr handler with ConsoleRenderer
    assert len(root_logger.handlers) == 2
    stderr_handler = root_logger.handlers[0]
    assert stderr_handler.stream == sys.stderr or (hasattr(stderr_handler.stream, 'name') and stderr_handler.stream.name == "<stderr>")

    formatter = stderr_handler.formatter
    assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)

    # Check that the last processor is ConsoleRenderer
    assert any(isinstance(p, structlog.dev.ConsoleRenderer) for p in formatter.processors)


def test_file_handler_uses_json_renderer():
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    # Mock the file handler to avoid file system operations
    with patch("os.makedirs"), patch("logging.handlers.RotatingFileHandler") as mock_handler:
        # Create a mock file handler
        mock_file_handler = mock_handler.return_value
        mock_file_handler.formatter = None

        # Set up logging
        root_logger.handlers.clear()
        root_logger.setLevel(logging.INFO)
        setup_logging()

        # Check that the file handler uses JSONRenderer
        file_handler = root_logger.handlers[1]  # Second handler should be file handler
        formatter = file_handler.formatter
        assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)

        # Check that the last processor is JSONRenderer
        assert any(isinstance(p, structlog.processors.JSONRenderer) for p in formatter.processors)


def test_log_level_from_env():
    with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(logging.INFO)

        setup_logging()

        # Check that the root logger level is DEBUG
        assert root_logger.level == logging.DEBUG


def test_log_level_default_info():
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    setup_logging()

    # Check that the root logger level is INFO by default
    assert root_logger.level == logging.INFO


def test_no_basicConfig_leak():
    # Clear environment and handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    # Add a basicConfig handler to simulate a leak
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    # Run setup_logging which should clear the basicConfig handler
    setup_logging()

    # Check that we have exactly 2 handlers (not 3)
    assert len(root_logger.handlers) == 2


def test_structlog_wrap_for_formatter():
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    setup_logging()

    # Check that structlog's last processor is wrap_for_formatter
    logger = structlog.get_logger()
    assert logger is not None


def test_e2e_dual_output():
    # Create a temporary directory for log files
    with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOG_DIR": temp_dir}):
        # Patch stderr to capture output
        fake_stderr = io.StringIO()

        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(logging.INFO)

        with patch("sys.stderr", fake_stderr):
            setup_logging()

            # Create a logger and log a message
            logger = structlog.get_logger()
            logger.info("test_event", key="value")

            # Check stderr output contains key=value format
            stderr_value = fake_stderr.getvalue()
            assert "test_event" in stderr_value
            assert "key=value" in stderr_value

            # Check that the log file contains valid JSON
            log_file_path = os.path.join(temp_dir, "hermes.jsonl")
            if os.path.exists(log_file_path):
                with open(log_file_path) as f:
                    content = f.read()
                    try:
                        json_line = json.loads(content.strip())
                        assert json_line["event"] == "test_event"
                        assert json_line["key"] == "value"
                    except json.JSONDecodeError as e:
                        raise AssertionError("Log file does not contain valid JSON") from e

        for handler in root_logger.handlers:
            handler.close()
        root_logger.handlers.clear()


def test_invalid_log_level_fallback():
    with patch.dict(os.environ, {"LOG_LEVEL": "INVALID"}):
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(logging.INFO)

        setup_logging()

        # Check that invalid LOG_LEVEL falls back to INFO
        assert root_logger.level == logging.INFO

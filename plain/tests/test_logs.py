import json
import logging
from io import StringIO

import pytest

from plain.logs import app_logger
from plain.logs.app import AppLogger
from plain.logs.configure import configure_logging
from plain.logs.formatters import JSONFormatter, KeyValueFormatter


class TestLoggingConfiguration:
    """Test that logging configuration sets up loggers correctly."""

    def test_configure_logging_basic(self):
        """Test basic logging configuration."""
        configure_logging(
            plain_log_level=logging.INFO,
            app_log_level=logging.WARNING,
            app_log_format="standard",
        )

        plain_logger = logging.getLogger("plain")
        app_logger = logging.getLogger("app")

        assert plain_logger.level == logging.INFO
        assert app_logger.level == logging.WARNING
        assert not plain_logger.propagate
        assert not app_logger.propagate

    def test_nested_logger_inheritance(self):
        """Test that nested loggers inherit settings from parent loggers."""
        configure_logging(
            plain_log_level=logging.ERROR,
            app_log_level=logging.DEBUG,
            app_log_format="standard",
        )

        # Test both nested and deeply nested loggers
        plain_nested = logging.getLogger("plain.module.submodule")
        app_nested = logging.getLogger("app.module.submodule")

        assert plain_nested.getEffectiveLevel() == logging.ERROR
        assert app_nested.getEffectiveLevel() == logging.DEBUG


class TestLoggerFormats:
    """Test different logging formats work correctly."""

    def setup_method(self):
        """Reset logging configuration before each test."""
        for logger_name in ["plain", "app"]:
            logger = logging.getLogger(logger_name)
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)

    def test_json_format_output(self):
        """Test JSON format produces valid JSON."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter("%(json)s"))

        logger = AppLogger("test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("Test message", context={"key": "value"})

        output = stream.getvalue().strip()
        parsed = json.loads(output)

        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test message"
        assert parsed["logger"] == "test"
        assert parsed["key"] == "value"
        assert "timestamp" in parsed

    def test_keyvalue_format_output(self):
        """Test KV format produces key-value pairs with proper escaping."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(
            KeyValueFormatter("[%(levelname)s] %(message)s %(keyvalue)s")
        )

        logger = AppLogger("test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info(
            "Test",
            context={
                "key": "value",
                "spaces": "value with spaces",
                "quotes": 'has "quotes"',
            },
        )

        output = stream.getvalue().strip()
        assert "[INFO] Test" in output
        assert "key=value" in output
        assert 'spaces="value with spaces"' in output
        assert 'quotes="has \\"quotes\\""' in output


class TestAppLogger:
    """Test AppLogger specific functionality."""

    def test_app_logger_instance_and_kwargs(self):
        """Test AppLogger instance and kwargs functionality."""
        assert isinstance(app_logger, AppLogger)

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter("%(json)s"))

        logger = AppLogger("test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("Test message", context={"user_id": 123, "action": "login"})

        output = stream.getvalue().strip()
        parsed = json.loads(output)
        assert parsed["user_id"] == 123
        assert parsed["action"] == "login"

    def test_context_management(self):
        """Test AppLogger context management and restoration."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter("%(json)s"))

        logger = AppLogger("test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Set persistent context
        logger.context["request_id"] = "req-123"

        # Use temporary context
        with logger.include_context(user_id=456):
            logger.info("Inside context")

        logger.info("Outside context")

        output = stream.getvalue()
        lines = [json.loads(line) for line in output.strip().split("\n") if line]

        # First log should have both request_id and user_id
        assert lines[0]["request_id"] == "req-123"
        assert lines[0]["user_id"] == 456

        # Second log should only have request_id
        assert lines[1]["request_id"] == "req-123"
        assert "user_id" not in lines[1]

        # Test context restoration after exception
        original_context = logger.context.copy()
        try:
            with logger.include_context(temporary="temp"):
                raise ValueError("Test exception")
        except ValueError:
            pass

        assert logger.context == original_context

    def test_standard_logging_features(self):
        """Test standard logging features like exc_info work correctly."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter("%(json)s"))

        logger = AppLogger("test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        try:
            raise ValueError("Test exception")
        except ValueError:
            logger.error("Error occurred", exc_info=True, context={"user_id": 123})

        output = stream.getvalue()
        json_line = output.split("\n")[0]
        parsed = json.loads(json_line)

        assert parsed["message"] == "Error occurred"
        assert parsed["user_id"] == 123
        assert "exception" in parsed
        assert "ValueError: Test exception" in parsed["exception"]

    def test_extra_vs_context_separation(self):
        """Test that extra parameters and context system are separate."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter("%(json)s"))

        logger = AppLogger("test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Standard extra won't appear in JSONFormatter, context will
        logger.info(
            "Test message",
            extra={"standard_extra": "ignored"},
            stacklevel=2,  # Standard param, won't appear
            context={"user_id": 456},  # Context param, will appear
        )

        parsed = json.loads(stream.getvalue().strip())
        assert "standard_extra" not in parsed
        assert "stacklevel" not in parsed
        assert parsed["user_id"] == 456

    def test_reserved_context_key_error(self):
        """Test that using 'context' key in extra raises an error."""
        logger = AppLogger("test")
        logger.setLevel(logging.INFO)

        with pytest.raises(ValueError, match="The 'context' key in extra is reserved"):
            logger.info("Test", extra={"context": {"user_id": 123}})

    def test_force_debug_functionality(self):
        """Test debug mode forcing and reference counting."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

        logger = AppLogger("test")
        logging.Logger.manager.loggerDict["test"] = logger
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)

        # Normal debug should be filtered
        logger.debug("Should not appear")

        # Test context manager
        with logger.force_debug():
            logger.debug("Context manager debug")
            # Test nested context managers
            with logger.force_debug():
                logger.debug("Nested debug")

        # Test manual control
        logger.debug_mode.start()
        logger.debug("Manual debug")
        logger.debug_mode.end()

        logger.debug("Should not appear again")

        output = stream.getvalue()
        lines = [line for line in output.strip().split("\n") if line]
        assert len(lines) == 3
        assert "Context manager debug" in output
        assert "Nested debug" in output
        assert "Manual debug" in output


class TestLogLevels:
    """Test that log levels work correctly."""

    def test_log_level_filtering(self):
        """Test that log levels filter messages correctly."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

        logger = AppLogger("test")
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)

        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")

        output = stream.getvalue()
        # Only WARNING and ERROR should appear
        assert "WARNING: Warning message" in output
        assert "ERROR: Error message" in output
        assert "Debug message" not in output
        assert "Info message" not in output


@pytest.fixture(autouse=True)
def cleanup_loggers():
    """Clean up loggers after each test to avoid interference."""
    yield

    # Remove custom loggers from the manager
    for logger_name in list(logging.root.manager.loggerDict.keys()):
        if logger_name.startswith(("plain", "app", "test")):
            del logging.root.manager.loggerDict[logger_name]

    # Clear handlers from any remaining loggers
    for logger_name in ["plain", "app"]:
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

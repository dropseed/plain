import logging
import sys
from typing import TextIO

from .filters import DebugInfoFilter, WarningErrorCriticalFilter
from .formatters import JSONFormatter, KeyValueFormatter


def attach_log_handlers(
    *,
    logger: logging.Logger,
    info_stream: TextIO,
    warning_stream: TextIO,
    formatter: logging.Formatter,
) -> None:
    """Attach two handlers to a logger that split by log level.

    INFO and below go to info_stream, WARNING and above go to warning_stream.
    """
    # DEBUG and INFO handler
    info_handler = logging.StreamHandler(info_stream)
    info_handler.addFilter(DebugInfoFilter())
    info_handler.setFormatter(formatter)
    logger.addHandler(info_handler)

    # WARNING, ERROR, and CRITICAL handler
    warning_handler = logging.StreamHandler(warning_stream)
    warning_handler.addFilter(WarningErrorCriticalFilter())
    warning_handler.setFormatter(formatter)
    logger.addHandler(warning_handler)


def create_log_formatter(log_format: str) -> logging.Formatter:
    """Create a formatter based on the log format setting."""
    match log_format:
        case "json":
            return JSONFormatter("%(json)s")
        case "keyvalue":
            return KeyValueFormatter("[%(levelname)s] %(message)s %(keyvalue)s")
        case _:
            raise ValueError(
                f"Invalid LOG_FORMAT: {log_format!r}. Must be 'keyvalue' or 'json'."
            )


def configure_logging(
    *,
    plain_log_level: int | str,
    app_log_level: int | str,
    app_log_format: str,
    log_stream: str = "split",
) -> None:
    # Determine which streams to use based on log_stream setting
    if log_stream == "split":
        info_stream = sys.stdout
        warning_stream = sys.stderr
    elif log_stream == "stdout":
        info_stream = sys.stdout
        warning_stream = sys.stdout
    else:  # stderr (or any other value defaults to stderr for backwards compat)
        info_stream = sys.stderr
        warning_stream = sys.stderr

    # Determine formatter based on app_log_format
    formatter = create_log_formatter(app_log_format)

    # Create and configure the plain logger using AppLogger for structured formatting
    from .app import AppLogger, app_logger

    plain_logger = AppLogger("plain")
    plain_logger.setLevel(plain_log_level)
    attach_log_handlers(
        logger=plain_logger,
        info_stream=info_stream,
        warning_stream=warning_stream,
        formatter=formatter,
    )
    plain_logger.propagate = False

    # Register so getLogger("plain") returns our AppLogger and children inherit handlers
    logging.root.manager.loggerDict["plain"] = plain_logger

    # Configure the existing app_logger
    app_logger.setLevel(app_log_level)
    app_logger.propagate = False

    attach_log_handlers(
        logger=app_logger,
        info_stream=info_stream,
        warning_stream=warning_stream,
        formatter=formatter,
    )

    # Register the app_logger in the logging system so getLogger("app") returns it
    logging.root.manager.loggerDict["app"] = app_logger

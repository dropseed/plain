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

    # Create and configure the plain logger (uses standard Logger, not AppLogger)
    plain_logger = logging.getLogger("plain")
    plain_logger.setLevel(plain_log_level)
    attach_log_handlers(
        logger=plain_logger,
        info_stream=info_stream,
        warning_stream=warning_stream,
        formatter=logging.Formatter("[%(levelname)s] %(message)s"),
    )
    plain_logger.propagate = False

    # Configure the existing app_logger
    from .app import app_logger

    app_logger.setLevel(app_log_level)
    app_logger.propagate = False

    # Determine formatter based on app_log_format
    match app_log_format:
        case "json":
            formatter = JSONFormatter("%(json)s")
        case "keyvalue":
            formatter = KeyValueFormatter("[%(levelname)s] %(message)s %(keyvalue)s")
        case _:
            formatter = logging.Formatter("[%(levelname)s] %(message)s")

    attach_log_handlers(
        logger=app_logger,
        info_stream=info_stream,
        warning_stream=warning_stream,
        formatter=formatter,
    )

    # Register the app_logger in the logging system so getLogger("app") returns it
    logging.root.manager.loggerDict["app"] = app_logger

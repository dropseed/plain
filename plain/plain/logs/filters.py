import logging


class DebugInfoFilter(logging.Filter):
    """Filter that only allows DEBUG and INFO log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= logging.INFO


class WarningErrorCriticalFilter(logging.Filter):
    """Filter that only allows WARNING, ERROR, and CRITICAL log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING

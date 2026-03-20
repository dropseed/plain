from __future__ import annotations

import json
import logging
from typing import Any

# Standard LogRecord attributes that are NOT user context.
# Everything else on the record is treated as structured context data.
_BASE_RECORD = logging.LogRecord("", 0, "", 0, "", (), None)
_BASE_RECORD_ATTR_COUNT = len(_BASE_RECORD.__dict__)
_STANDARD_RECORD_ATTRS = frozenset(_BASE_RECORD.__dict__.keys()) | {
    "message",
    "asctime",
    "keyvalue",
    "json",
}


def _get_context(record: logging.LogRecord) -> dict[str, Any]:
    """Extract user context from a LogRecord (everything not a standard attribute)."""
    if len(record.__dict__) <= _BASE_RECORD_ATTR_COUNT:
        return {}
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STANDARD_RECORD_ATTRS
    }


class KeyValueFormatter(logging.Formatter):
    """Formatter that outputs key-value pairs from structured context."""

    def format(self, record: logging.LogRecord) -> str:
        kv_pairs = []

        for key, value in _get_context(record).items():
            formatted_value = self._format_value(value)
            kv_pairs.append(f"{key}={formatted_value}")

        # Add the keyvalue attribute to the record for %(keyvalue)s substitution
        record.keyvalue = " ".join(kv_pairs)

        # Let the parent formatter handle the format string with %(keyvalue)s
        return super().format(record)

    @staticmethod
    def _format_value(value: Any) -> str:
        """Format a value for key-value output."""
        if isinstance(value, str):
            s = value
        else:
            s = str(value)

        if '"' in s:
            # Escape quotes and surround it
            s = s.replace('"', '\\"')
            s = f'"{s}"'
        elif s == "":
            # Quote empty strings instead of printing nothing
            s = '""'
        elif any(char in s for char in [" ", "/", "'", ":", "=", "."]):
            # Surround these with quotes for parsers
            s = f'"{s}"'

        return s


class JSONFormatter(logging.Formatter):
    """Formatter that outputs JSON with structured context."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Add structured context data
        log_obj.update(_get_context(record))

        # Handle exceptions
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Add the json attribute to the record for %(json)s substitution
        record.json = json.dumps(log_obj, default=str, ensure_ascii=False)

        # Let the parent formatter handle the format string with %(json)s
        return super().format(record)

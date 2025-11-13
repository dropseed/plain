from __future__ import annotations

import json
import logging
from typing import Any


class KeyValueFormatter(logging.Formatter):
    """Formatter that outputs key-value pairs from Plain's context system."""

    def format(self, record: logging.LogRecord) -> str:
        # Build key-value pairs from context
        kv_pairs = []

        # Look for Plain's context data
        if hasattr(record, "context") and isinstance(record.context, dict):
            for key, value in record.context.items():
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
    """Formatter that outputs JSON from Plain's context system, with optional format string."""

    def format(self, record: logging.LogRecord) -> str:
        # Build the JSON object from Plain's context data
        log_obj = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Add Plain's context data to the main JSON object
        if hasattr(record, "context") and isinstance(record.context, dict):
            log_obj.update(record.context)  # type: ignore[arg-type]

        # Handle exceptions
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Add the json attribute to the record for %(json)s substitution
        record.json = json.dumps(log_obj, default=str, ensure_ascii=False)

        # Let the parent formatter handle the format string with %(json)s
        return super().format(record)

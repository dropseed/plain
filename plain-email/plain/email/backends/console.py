"""
Email backend that writes messages to console instead of sending them.
"""

from __future__ import annotations

import sys
import threading
from typing import TYPE_CHECKING, Any

from .base import BaseEmailBackend

if TYPE_CHECKING:
    from ..message import EmailMessage


class EmailBackend(BaseEmailBackend):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.stream = kwargs.pop("stream", sys.stdout)
        self._lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def write_message(self, message: EmailMessage) -> None:
        msg = message.message()
        msg_data = msg.as_bytes()
        msg_charset = msg.get_charset()
        if msg_charset is None:
            charset = "utf-8"
        elif isinstance(msg_charset, str):
            charset = msg_charset
        else:
            charset = msg_charset.get_output_charset() or "utf-8"
        msg_data = msg_data.decode(charset)
        self.stream.write(f"{msg_data}\n")
        self.stream.write("-" * 79)
        self.stream.write("\n")

    def send_messages(self, email_messages: list[EmailMessage]) -> int:
        """Write all messages to the stream in a thread-safe way."""
        if not email_messages:
            return 0
        msg_count = 0
        with self._lock:
            try:
                stream_created = self.open()
                for message in email_messages:
                    self.write_message(message)
                    self.stream.flush()  # flush after each message
                    msg_count += 1
                if stream_created:
                    self.close()
            except Exception:
                if not self.fail_silently:
                    raise
        return msg_count

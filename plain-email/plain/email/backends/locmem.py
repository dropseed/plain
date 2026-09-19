"""Email backend that captures messages in memory for testing.

Messages handed to ``send_messages`` are appended to the module-level
``outbox`` list instead of being delivered. During test runs the email test
lifecycle routes ``EMAIL_BACKEND`` here and clears ``outbox`` around each
test — import it via ``plain.email.test``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BaseEmailBackend

if TYPE_CHECKING:
    from ..message import EmailMessage

__all__ = ["EmailBackend", "outbox"]

# Module-level, not per-instance: get_connection() builds a fresh backend for
# every send, so captured mail has to accumulate somewhere shared.
outbox: list[EmailMessage] = []


class EmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages: list[EmailMessage]) -> int:
        outbox.extend(email_messages)
        return len(email_messages)

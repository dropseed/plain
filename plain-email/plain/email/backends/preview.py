"""Email backend for previewing sent messages during development.

Messages are captured as .eml files in ``.plain/emails/`` so you can inspect
them — either via the Plain toolbar panel (when ``plain.toolbar`` is
installed) or by opening the .eml in Mail.app. Nothing is delivered to a real
SMTP server.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from plain.runtime import PLAIN_TEMP_PATH
from plain.utils.crypto import get_random_string

from .base import BaseEmailBackend

if TYPE_CHECKING:
    from ..message import EmailMessage


__all__ = ["EmailBackend"]


EMAIL_DIR = PLAIN_TEMP_PATH / "emails"


class EmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages: list[EmailMessage]) -> int:
        if not email_messages:
            return 0

        EMAIL_DIR.mkdir(parents=True, exist_ok=True)

        count = 0
        for message in email_messages:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            stem = f"{timestamp}-{get_random_string(8)}"
            (EMAIL_DIR / f"{stem}.eml").write_bytes(
                message.message().as_bytes(linesep="\r\n")
            )
            count += 1
        return count

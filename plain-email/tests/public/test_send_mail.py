from __future__ import annotations

from plain.email import send_mail, send_mass_mail
from plain.email.backends.base import BaseEmailBackend


class MinimalBackend(BaseEmailBackend):
    """A backend that accepts no extra __init__ kwargs."""

    def __init__(self) -> None:
        self.sent_messages: list = []

    def send_messages(self, email_messages):
        self.sent_messages.extend(email_messages)
        return len(email_messages)


def test_send_mail_with_custom_backend(settings):
    settings.EMAIL_BACKEND = (
        f"{MinimalBackend.__module__}.{MinimalBackend.__qualname__}"
    )

    # This should work even though MinimalBackend doesn't accept username/password
    count = send_mail(
        "Subject",
        "Body",
        "from@example.com",
        ["to@example.com"],
    )
    assert count == 1


def test_send_mass_mail_with_custom_backend(settings):
    settings.EMAIL_BACKEND = (
        f"{MinimalBackend.__module__}.{MinimalBackend.__qualname__}"
    )

    count = send_mass_mail(
        (
            ("Subject 1", "Body 1", "from@example.com", ["to@example.com"]),
            ("Subject 2", "Body 2", "from@example.com", ["to@example.com"]),
        )
    )
    assert count == 2

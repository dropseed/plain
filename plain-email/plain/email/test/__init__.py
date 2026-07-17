"""
Email test helpers.

During a test run, `EMAIL_BACKEND` is routed to the in-memory backend and
`outbox` collects every email sent. The outbox is cleared between tests.

    from plain.email.test import outbox

    def test_signup_sends_welcome():
        Client().post("/signup/", form_data={"email": "a@example.com"})
        assert len(outbox) == 1
        assert outbox[0].to == ["a@example.com"]
"""

from __future__ import annotations

from plain.email.backends.locmem import outbox

from .lifecycle import EmailTestLifecycle

__all__ = ["outbox", "EmailTestLifecycle"]

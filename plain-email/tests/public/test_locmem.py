"""Tests for the in-memory email backend and the ``outbox`` list."""

from __future__ import annotations

from plain.email import send_mail
from plain.email.test import outbox


def test_outbox_captures_sent_email():
    assert outbox == []

    send_mail("Hello", "Body text", "from@example.com", ["to@example.com"])

    assert len(outbox) == 1
    assert outbox[0].subject == "Hello"
    assert outbox[0].to == ["to@example.com"]


def test_outbox_is_empty_at_test_start():
    # Even though another test sends mail, the outbox is cleared around
    # every test — captured email never leaks between tests.
    assert outbox == []

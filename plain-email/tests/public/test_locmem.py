"""Tests for the in-memory email backend and the ``mailoutbox`` fixture."""

from __future__ import annotations

from plain.email import send_mail


def test_mailoutbox_captures_sent_email(mailoutbox):
    assert mailoutbox == []

    send_mail("Hello", "Body text", "from@example.com", ["to@example.com"])

    assert len(mailoutbox) == 1
    assert mailoutbox[0].subject == "Hello"
    assert mailoutbox[0].to == ["to@example.com"]


def test_mailoutbox_is_empty_at_test_start(mailoutbox):
    # Even though another test sends mail, the fixture clears the outbox
    # around every test — captured email never leaks between tests.
    assert mailoutbox == []

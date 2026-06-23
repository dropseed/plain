from __future__ import annotations

import pytest

from plain.email.message import EmailMessage


def test_bcc_in_headers_raises():
    """Bcc must never leak into the visible message headers."""
    message = EmailMessage(
        subject="Hi",
        body="Body",
        from_email="from@example.com",
        to=["to@example.com"],
        headers={"Bcc": "secret@example.com"},
    )
    with pytest.raises(ValueError, match='Use the "bcc" argument'):
        message.message()


def test_to_cc_reply_to_not_duplicated_via_headers():
    """To/Cc/Reply-To passed via headers don't duplicate the instance headers."""
    message = EmailMessage(
        subject="Hi",
        body="Body",
        from_email="from@example.com",
        to=["real@example.com"],
        cc=["cc@example.com"],
        reply_to=["reply@example.com"],
        headers={
            "To": "spoof@example.com",
            "Cc": "spoof@example.com",
            "Reply-To": "spoof@example.com",
        },
    ).message()

    assert message.get_all("To") == ["spoof@example.com"]
    assert message.get_all("Cc") == ["spoof@example.com"]
    assert message.get_all("Reply-To") == ["spoof@example.com"]

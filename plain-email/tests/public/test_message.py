"""Tests for building ``EmailMessage`` objects: headers, recipients,
attachments, HTML alternatives, and header-injection protection.
"""

from __future__ import annotations

from plain.email import send_mail
from plain.email.message import (
    BadHeaderError,
    EmailMessage,
    EmailMultiAlternatives,
)
from plain.email.test import outbox
from plain.test import override_settings, raises


def test_message_sets_core_headers():
    email = EmailMessage(
        subject="Hi",
        body="Body",
        from_email="from@example.com",
        to=["a@example.com", "b@example.com"],
        cc=["c@example.com"],
        reply_to=["reply@example.com"],
    )
    msg = email.message()

    assert msg["Subject"] == "Hi"
    assert msg["From"] == "from@example.com"
    assert msg["To"] == "a@example.com, b@example.com"
    assert msg["Cc"] == "c@example.com"
    assert msg["Reply-To"] == "reply@example.com"
    assert msg.get_payload() == "Body"


def test_recipients_include_to_cc_and_bcc():
    email = EmailMessage(
        subject="Hi",
        body="Body",
        from_email="from@example.com",
        to=["to@example.com"],
        cc=["cc@example.com"],
        bcc=["bcc@example.com"],
    )
    assert email.recipients() == [
        "to@example.com",
        "cc@example.com",
        "bcc@example.com",
    ]


def test_bcc_is_not_exposed_in_headers():
    email = EmailMessage(
        subject="Hi",
        body="Body",
        from_email="from@example.com",
        to=["to@example.com"],
        bcc=["secret@example.com"],
    )
    msg = email.message()
    # BCC recipients must never leak into the rendered headers.
    assert "secret@example.com" not in msg.as_string()


def test_default_from_email_is_used():
    with override_settings(EMAIL_DEFAULT_FROM="default@example.com"):
        email = EmailMessage(subject="Hi", body="Body", to=["to@example.com"])
        assert email.message()["From"] == "default@example.com"


def test_header_injection_is_blocked():
    """A newline in a header value must raise rather than silently allow a
    second injected header (email header injection)."""
    email = EmailMessage(
        subject="Legit\nBcc: attacker@example.com",
        body="Body",
        from_email="from@example.com",
        to=["to@example.com"],
    )
    with raises(BadHeaderError):
        email.message()


def test_string_recipient_is_rejected():
    with raises(TypeError):
        EmailMessage(
            subject="Hi",
            body="Body",
            from_email="from@example.com",
            to="not-a-list@example.com",  # ty: ignore[invalid-argument-type]
        )


def test_attachment_produces_multipart_mixed():
    email = EmailMessage(
        subject="Hi",
        body="Body",
        from_email="from@example.com",
        to=["to@example.com"],
    )
    email.attach("notes.txt", "file contents", "text/plain")
    msg = email.message()

    assert msg.is_multipart()
    assert msg.get_content_subtype() == "mixed"


def test_html_alternative_produces_multipart_alternative():
    email = EmailMultiAlternatives(
        subject="Hi",
        body="Plain body",
        from_email="from@example.com",
        to=["to@example.com"],
    )
    email.attach_alternative("<p>HTML body</p>", "text/html")
    msg = email.message()

    assert msg.is_multipart()
    assert msg.get_content_subtype() == "alternative"
    payload_types = {
        part.get_content_type()  # ty: ignore[unresolved-attribute]
        for part in msg.get_payload()
    }
    assert payload_types == {"text/plain", "text/html"}


def test_send_mail_with_html_message_captured():
    send_mail(
        "Subject",
        "Plain body",
        "from@example.com",
        ["to@example.com"],
        html_message="<p>HTML body</p>",
    )

    assert len(outbox) == 1
    sent = outbox[0]
    assert sent.body == "Plain body"
    assert ("<p>HTML body</p>", "text/html") in sent.alternatives

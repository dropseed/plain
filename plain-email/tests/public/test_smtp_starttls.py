from __future__ import annotations

import smtplib

import pytest

from plain.email.backends.smtp import EmailBackend
from plain.email.message import EmailMessage


class StartTLSFailsSMTP:
    """A stub SMTP connection whose STARTTLS handshake always fails.

    Tracks every connection instance created and records whether any mail was
    sent over a connection that never completed STARTTLS (i.e. plaintext).
    """

    instances: list[StartTLSFailsSMTP] = []

    def __init__(self, host, port, **kwargs):
        self.host = host
        self.port = port
        self.tls_started = False
        self.sent = []
        self.closed = False
        StartTLSFailsSMTP.instances.append(self)

    def starttls(self, context=None):
        raise smtplib.SMTPException("STARTTLS not supported by server")

    def login(self, username, password):  # pragma: no cover - never reached
        pass

    def sendmail(self, from_addr, to_addrs, msg):
        self.sent.append((from_addr, to_addrs, msg))

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


class StartTLSFailsBackend(EmailBackend):
    @property
    def connection_class(self):
        return StartTLSFailsSMTP


@pytest.fixture(autouse=True)
def _reset_instances():
    StartTLSFailsSMTP.instances = []
    yield
    StartTLSFailsSMTP.instances = []


def test_failed_starttls_does_not_retain_usable_connection():
    """A STARTTLS failure must not leave a usable (plaintext) connection behind."""
    backend = StartTLSFailsBackend(
        host="smtp.example.com",
        port=587,
        use_tls=True,
        use_ssl=False,
    )

    with pytest.raises(smtplib.SMTPException):
        backend.open()

    # The plaintext socket was created but never promoted to self.connection.
    assert backend.connection is None
    # And the leftover partial connection is tracked for cleanup, not reuse.
    assert backend._partial_connection is not None


def test_failed_starttls_does_not_send_over_plaintext_connection():
    """After a failed STARTTLS, a later send must not reuse the plaintext socket."""
    backend = StartTLSFailsBackend(
        host="smtp.example.com",
        port=587,
        use_tls=True,
        use_ssl=False,
    )

    message = EmailMessage(
        "Subject",
        "Body",
        "from@example.com",
        ["to@example.com"],
    )

    # First attempt fails during STARTTLS and propagates out of send_messages.
    with pytest.raises(smtplib.SMTPException):
        backend.send_messages([message])

    # A second send against the same (reused/persistent) backend must again
    # attempt STARTTLS rather than silently reusing the leftover plaintext
    # socket, so it fails the same way and never sends mail.
    with pytest.raises(smtplib.SMTPException):
        backend.send_messages([message])

    # No connection ever completed STARTTLS, and nothing was transmitted.
    assert all(not conn.tls_started for conn in StartTLSFailsSMTP.instances)
    assert all(conn.sent == [] for conn in StartTLSFailsSMTP.instances)
    # The leftover partial from the first attempt was closed on the second open().
    assert StartTLSFailsSMTP.instances[0].closed

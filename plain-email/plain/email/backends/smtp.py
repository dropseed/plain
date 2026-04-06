"""SMTP email backend class."""

from __future__ import annotations

import smtplib
import ssl
import threading
from functools import cached_property
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.semconv.attributes.server_attributes import (
    SERVER_ADDRESS,
    SERVER_PORT,
)
from opentelemetry.trace import SpanKind

from plain.runtime import settings
from plain.utils.otel import format_exception_type

from ..backends.base import BaseEmailBackend
from ..message import _sanitize_address
from ..utils import _DNS_NAME

if TYPE_CHECKING:
    from ..message import EmailMessage

tracer = trace.get_tracer("plain.email")


class EmailBackend(BaseEmailBackend):
    """
    A wrapper that manages the SMTP network connection.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool | None = None,
        use_ssl: bool | None = None,
        timeout: int | None = None,
        ssl_keyfile: str | None = None,
        ssl_certfile: str | None = None,
    ) -> None:
        self.host = host or settings.EMAIL_HOST
        self.port = port or settings.EMAIL_PORT
        self.username = settings.EMAIL_HOST_USER if username is None else username
        self.password = settings.EMAIL_HOST_PASSWORD if password is None else password
        self.use_tls = settings.EMAIL_USE_TLS if use_tls is None else use_tls
        self.use_ssl = settings.EMAIL_USE_SSL if use_ssl is None else use_ssl
        self.timeout = settings.EMAIL_TIMEOUT if timeout is None else timeout
        self.ssl_keyfile = (
            settings.EMAIL_SSL_KEYFILE if ssl_keyfile is None else ssl_keyfile
        )
        self.ssl_certfile = (
            settings.EMAIL_SSL_CERTFILE if ssl_certfile is None else ssl_certfile
        )
        if self.use_ssl and self.use_tls:
            raise ValueError(
                "EMAIL_USE_TLS/EMAIL_USE_SSL are mutually exclusive, so only set "
                "one of those settings to True."
            )
        self.connection = None
        self._lock = threading.RLock()

    @property
    def connection_class(self) -> type[smtplib.SMTP]:
        return smtplib.SMTP_SSL if self.use_ssl else smtplib.SMTP

    @cached_property
    def ssl_context(self) -> ssl.SSLContext:
        if self.ssl_certfile or self.ssl_keyfile:
            ssl_context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.load_cert_chain(self.ssl_certfile, self.ssl_keyfile)
            return ssl_context
        else:
            return ssl.create_default_context()

    def open(self) -> bool:
        """
        Ensure an open connection to the email server. Return whether or not a
        new connection was required (True or False).
        """
        if self.connection:
            # Nothing to do if the connection is already open.
            return False

        # If local_hostname is not specified, socket.getfqdn() gets used.
        # For performance, we use the cached FQDN for local_hostname.
        connection_params: dict[str, Any] = {"local_hostname": _DNS_NAME.get_fqdn()}
        if self.timeout is not None:
            connection_params["timeout"] = self.timeout
        if self.use_ssl:
            connection_params["context"] = self.ssl_context
        self.connection = self.connection_class(
            self.host, self.port, **connection_params
        )

        # TLS/SSL are mutually exclusive, so only attempt TLS over
        # non-secure connections.
        if not self.use_ssl and self.use_tls:
            self.connection.starttls(context=self.ssl_context)
        if self.username and self.password:
            self.connection.login(self.username, self.password)
        return True

    def close(self) -> None:
        """Close the connection to the email server."""
        if self.connection is None:
            return
        try:
            try:
                self.connection.quit()
            except (ssl.SSLError, smtplib.SMTPServerDisconnected):
                # This happens when calling quit() on a TLS connection
                # sometimes, or when the connection was already disconnected
                # by the server.
                self.connection.close()
        finally:
            self.connection = None

    def send_messages(self, email_messages: list[EmailMessage]) -> int:
        """
        Send one or more EmailMessage objects and return the number of email
        messages sent.
        """
        if not email_messages:
            return 0
        with self._lock:
            new_conn_created = self.open()
            num_sent = 0
            try:
                for message in email_messages:
                    sent = self._send(message)
                    if sent:
                        num_sent += 1
            finally:
                if new_conn_created:
                    self.close()
        return num_sent

    def _send(self, email_message: EmailMessage) -> bool:
        """A helper method that does the actual sending."""
        if not email_message.recipients():
            return False

        attrs: dict[str, Any] = {
            "email.system": "smtp",
            "email.recipients.count": len(email_message.recipients()),
            "email.has_attachments": bool(email_message.attachments),
        }
        if self.host:
            attrs[SERVER_ADDRESS] = self.host
        if self.port:
            attrs[SERVER_PORT] = self.port

        with tracer.start_as_current_span(
            "email.send",
            kind=SpanKind.CLIENT,
            attributes=attrs,
        ) as span:
            encoding = email_message.encoding or "utf-8"
            from_email = _sanitize_address(email_message.from_email, encoding)
            recipients = [
                _sanitize_address(addr, encoding) for addr in email_message.recipients()
            ]
            message = email_message.message()
            assert self.connection is not None, (
                "connection should be open before sending"
            )
            try:
                self.connection.sendmail(
                    from_email, recipients, message.as_bytes(linesep="\r\n")
                )
            except Exception as exc:
                # record_exception + set_status(ERROR) handled by the
                # context manager when the exception propagates out.
                # We only need to set error.type (SDK doesn't do this).
                span.set_attribute(ERROR_TYPE, format_exception_type(exc))
                raise
            return True

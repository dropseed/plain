"""
Tools for sending email.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.runtime import settings
from plain.utils.module_loading import import_string

if TYPE_CHECKING:
    from .backends.base import BaseEmailBackend

from .message import (
    DEFAULT_ATTACHMENT_MIME_TYPE,
    BadHeaderError,
    EmailMessage,
    EmailMultiAlternatives,
    SafeMIMEMultipart,
    SafeMIMEText,
    TemplateEmail,
    forbid_multi_line_headers,
    make_msgid,
)
from .utils import DNS_NAME, CachedDnsName

__all__ = [
    "CachedDnsName",
    "DNS_NAME",
    "EmailMessage",
    "EmailMultiAlternatives",
    "TemplateEmail",
    "SafeMIMEText",
    "SafeMIMEMultipart",
    "DEFAULT_ATTACHMENT_MIME_TYPE",
    "make_msgid",
    "BadHeaderError",
    "forbid_multi_line_headers",
    "get_connection",
    "send_mail",
    "send_mass_mail",
]


def get_connection(
    backend: str | None = None, fail_silently: bool = False, **kwds: Any
) -> BaseEmailBackend:
    """Load an email backend and return an instance of it.

    If backend is None (default), use settings.EMAIL_BACKEND.

    Both fail_silently and other keyword arguments are used in the
    constructor of the backend.
    """
    klass = import_string(backend or settings.EMAIL_BACKEND)
    return klass(fail_silently=fail_silently, **kwds)


def send_mail(
    subject: str,
    message: str,
    from_email: str | None,
    recipient_list: list[str],
    fail_silently: bool = False,
    auth_user: str | None = None,
    auth_password: str | None = None,
    connection: BaseEmailBackend | None = None,
    html_message: str | None = None,
) -> int:
    """
    Easy wrapper for sending a single message to a recipient list. All members
    of the recipient list will see the other recipients in the 'To' field.

    If from_email is None, use the EMAIL_DEFAULT_FROM setting.
    If auth_user is None, use the EMAIL_HOST_USER setting.
    If auth_password is None, use the EMAIL_HOST_PASSWORD setting.

    Note: The API for this method is frozen. New code wanting to extend the
    functionality should use the EmailMessage class directly.
    """
    connection = connection or get_connection(
        username=auth_user,
        password=auth_password,
        fail_silently=fail_silently,
    )
    mail = EmailMultiAlternatives(
        subject, message, from_email, recipient_list, connection=connection
    )
    if html_message:
        mail.attach_alternative(html_message, "text/html")

    return mail.send()


def send_mass_mail(
    datatuple: tuple[tuple[str, str, str, list[str]], ...],
    fail_silently: bool = False,
    auth_user: str | None = None,
    auth_password: str | None = None,
    connection: BaseEmailBackend | None = None,
) -> int:
    """
    Given a datatuple of (subject, message, from_email, recipient_list), send
    each message to each recipient list. Return the number of emails sent.

    If from_email is None, use the EMAIL_DEFAULT_FROM setting.
    If auth_user and auth_password are set, use them to log in.
    If auth_user is None, use the EMAIL_HOST_USER setting.
    If auth_password is None, use the EMAIL_HOST_PASSWORD setting.

    Note: The API for this method is frozen. New code wanting to extend the
    functionality should use the EmailMessage class directly.
    """
    connection = connection or get_connection(
        username=auth_user,
        password=auth_password,
        fail_silently=fail_silently,
    )
    messages = [
        EmailMessage(subject, message, sender, recipient, connection=connection)
        for subject, message, sender, recipient in datatuple
    ]
    return connection.send_messages(messages)

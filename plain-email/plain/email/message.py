from __future__ import annotations

import mimetypes
from email import charset as Charset
from email import encoders as Encoders
from email import generator, message_from_string
from email.errors import HeaderParseError
from email.header import Header
from email.headerregistry import Address
from email.headerregistry import (
    parser as headerregistry_parser,  # type: ignore[attr-defined]
)
from email.message import Message
from email.mime.base import MIMEBase
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, getaddresses, make_msgid
from io import BytesIO, StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from plain.runtime import settings
from plain.templates import Template, TemplateFileMissing
from plain.utils.encoding import force_str, punycode
from plain.utils.html import strip_tags

from .utils import DNS_NAME

if TYPE_CHECKING:
    from os import PathLike

    from .backends.base import BaseEmailBackend

# Don't BASE64-encode UTF-8 messages so that we avoid unwanted attention from
# some spam filters.
utf8_charset = Charset.Charset("utf-8")
utf8_charset.body_encoding = None  # type: ignore[assignment]  # Python defaults to BASE64
utf8_charset_qp = Charset.Charset("utf-8")
utf8_charset_qp.body_encoding = Charset.QP

# Default MIME type to use on attachments (if it is not explicitly given
# and cannot be guessed).
DEFAULT_ATTACHMENT_MIME_TYPE = "application/octet-stream"

RFC5322_EMAIL_LINE_LENGTH_LIMIT = 998


class BadHeaderError(ValueError):
    pass


# Header names that contain structured address data (RFC 5322).
ADDRESS_HEADERS = {
    "from",
    "sender",
    "reply-to",
    "to",
    "cc",
    "bcc",
    "resent-from",
    "resent-sender",
    "resent-to",
    "resent-cc",
    "resent-bcc",
}


def forbid_multi_line_headers(
    name: str, val: str, encoding: str | None
) -> tuple[str, str]:
    """Forbid multi-line headers to prevent header injection."""
    encoding = encoding or settings.DEFAULT_CHARSET
    val = str(val)  # val may be lazy
    if "\n" in val or "\r" in val:
        raise BadHeaderError(
            f"Header values can't contain newlines (got {val!r} for header {name!r})"
        )
    try:
        val.encode("ascii")
    except UnicodeEncodeError:
        if name.lower() in ADDRESS_HEADERS:
            val = ", ".join(
                sanitize_address(addr, encoding) for addr in getaddresses((val,))
            )
        else:
            val = Header(val, encoding).encode()
    else:
        if name.lower() == "subject":
            val = Header(val).encode()
    return name, val


def sanitize_address(addr: str | tuple[str, str], encoding: str) -> str:
    """
    Format a pair of (name, address) or an email address string.
    """
    address = None
    if not isinstance(addr, tuple):
        addr = force_str(addr)
        try:
            token, rest = headerregistry_parser.get_mailbox(addr)
        except (HeaderParseError, ValueError, IndexError):
            raise ValueError(f'Invalid address "{addr}"')
        else:
            if rest:
                # The entire email address must be parsed.
                raise ValueError(
                    f'Invalid address; only {token} could be parsed from "{addr}"'
                )
            nm = token.display_name or ""
            localpart = token.local_part
            domain = token.domain or ""
    else:
        nm, address = addr
        localpart, domain = address.rsplit("@", 1)

    address_parts = nm + localpart + domain
    if "\n" in address_parts or "\r" in address_parts:
        raise ValueError("Invalid address; address parts cannot contain newlines.")

    # Avoid UTF-8 encode, if it's possible.
    try:
        nm.encode("ascii")
        nm = Header(nm).encode()
    except UnicodeEncodeError:
        nm = Header(nm, encoding).encode()
    try:
        localpart.encode("ascii")
    except UnicodeEncodeError:
        localpart = Header(localpart, encoding).encode()
    domain = punycode(domain)

    parsed_address = Address(username=localpart, domain=domain)
    return formataddr((nm, parsed_address.addr_spec))


class MIMEMixin:
    def as_string(self, unixfrom: bool = False, linesep: str = "\n") -> str:
        """Return the entire formatted message as a string.
        Optional `unixfrom' when True, means include the Unix From_ envelope
        header.

        This overrides the default as_string() implementation to not mangle
        lines that begin with 'From '. See bug #13433 for details.
        """
        fp = StringIO()
        g = generator.Generator(fp, mangle_from_=False)
        g.flatten(self, unixfrom=unixfrom, linesep=linesep)
        return fp.getvalue()

    def as_bytes(self, unixfrom: bool = False, linesep: str = "\n") -> bytes:
        """Return the entire formatted message as bytes.
        Optional `unixfrom' when True, means include the Unix From_ envelope
        header.

        This overrides the default as_bytes() implementation to not mangle
        lines that begin with 'From '. See bug #13433 for details.
        """
        fp = BytesIO()
        g = generator.BytesGenerator(fp, mangle_from_=False)
        g.flatten(self, unixfrom=unixfrom, linesep=linesep)
        return fp.getvalue()


class SafeMIMEMessage(MIMEMixin, MIMEMessage):
    def __setitem__(self, name: str, val: str) -> None:
        # message/rfc822 attachments must be ASCII
        name, val = forbid_multi_line_headers(name, val, "ascii")
        MIMEMessage.__setitem__(self, name, val)


class SafeMIMEText(MIMEMixin, MIMEText):
    def __init__(
        self, _text: str, _subtype: str = "plain", _charset: str | None = None
    ) -> None:
        self.encoding = _charset
        MIMEText.__init__(self, _text, _subtype=_subtype, _charset=_charset)

    def __setitem__(self, name: str, val: str) -> None:
        name, val = forbid_multi_line_headers(name, val, self.encoding)
        MIMEText.__setitem__(self, name, val)

    def set_payload(
        self, payload: str, charset: str | Charset.Charset | None = None
    ) -> None:
        if charset == "utf-8" and not isinstance(charset, Charset.Charset):
            has_long_lines = any(
                len(line.encode()) > RFC5322_EMAIL_LINE_LENGTH_LIMIT
                for line in payload.splitlines()
            )
            # Quoted-Printable encoding has the side effect of shortening long
            # lines, if any (#22561).
            charset = utf8_charset_qp if has_long_lines else utf8_charset
        MIMEText.set_payload(self, payload, charset=charset)


class SafeMIMEMultipart(MIMEMixin, MIMEMultipart):
    def __init__(
        self,
        _subtype: str = "mixed",
        boundary: str | None = None,
        _subparts: list[Message] | None = None,
        encoding: str | None = None,
        **_params: Any,
    ) -> None:
        self.encoding = encoding
        MIMEMultipart.__init__(self, _subtype, boundary, _subparts, **_params)

    def __setitem__(self, name: str, val: str) -> None:
        name, val = forbid_multi_line_headers(name, val, self.encoding)
        MIMEMultipart.__setitem__(self, name, val)


class EmailMessage:
    """A container for email information."""

    content_subtype = "plain"
    mixed_subtype = "mixed"
    encoding: str | None = None  # None => use settings default

    def __init__(
        self,
        subject: str = "",
        body: str = "",
        from_email: str | None = None,
        to: list[str] | tuple[str, ...] | None = None,
        bcc: list[str] | tuple[str, ...] | None = None,
        connection: BaseEmailBackend | None = None,
        attachments: list[MIMEBase | tuple[str, str, str]] | None = None,
        headers: dict[str, str] | None = None,
        cc: list[str] | tuple[str, ...] | None = None,
        reply_to: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        """
        Initialize a single email message (which can be sent to multiple
        recipients).
        """
        if to:
            if isinstance(to, str):
                raise TypeError('"to" argument must be a list or tuple')
            self.to = list(to)
        else:
            self.to = []
        if cc:
            if isinstance(cc, str):
                raise TypeError('"cc" argument must be a list or tuple')
            self.cc = list(cc)
        else:
            self.cc = []
        if bcc:
            if isinstance(bcc, str):
                raise TypeError('"bcc" argument must be a list or tuple')
            self.bcc = list(bcc)
        else:
            self.bcc = []
        if reply_to:
            if isinstance(reply_to, str):
                raise TypeError('"reply_to" argument must be a list or tuple')
            self.reply_to = list(reply_to)
        else:
            self.reply_to = settings.EMAIL_DEFAULT_REPLY_TO or []
        self.from_email = from_email or settings.EMAIL_DEFAULT_FROM
        self.subject = subject
        self.body = body or ""
        self.attachments = []
        if attachments:
            for attachment in attachments:
                if isinstance(attachment, MIMEBase):
                    self.attach(attachment)
                else:
                    self.attach(*attachment)
        self.extra_headers = headers or {}
        self.connection = connection

    def get_connection(self, fail_silently: bool = False) -> BaseEmailBackend:
        from . import get_connection

        if not self.connection:
            self.connection = get_connection(fail_silently=fail_silently)
        return self.connection

    def message(self) -> SafeMIMEText | SafeMIMEMultipart:
        encoding = self.encoding or settings.DEFAULT_CHARSET
        msg = SafeMIMEText(self.body, self.content_subtype, encoding)
        msg = self._create_message(msg)
        msg["Subject"] = self.subject
        msg["From"] = self.extra_headers.get("From", self.from_email)
        self._set_list_header_if_not_empty(msg, "To", self.to)
        self._set_list_header_if_not_empty(msg, "Cc", self.cc)
        self._set_list_header_if_not_empty(msg, "Reply-To", self.reply_to)

        # Email header names are case-insensitive (RFC 2045), so we have to
        # accommodate that when doing comparisons.
        header_names = [key.lower() for key in self.extra_headers]
        if "date" not in header_names:
            # formatdate() uses stdlib methods to format the date, which use
            # the stdlib/OS concept of a timezone, however, Plain sets the
            # TZ environment variable based on the TIME_ZONE setting which
            # will get picked up by formatdate().
            msg["Date"] = formatdate(localtime=settings.EMAIL_USE_LOCALTIME)
        if "message-id" not in header_names:
            # Use cached DNS_NAME for performance
            msg["Message-ID"] = make_msgid(domain=str(DNS_NAME))
        for name, value in self.extra_headers.items():
            if name.lower() != "from":  # From is already handled
                msg[name] = value
        return msg

    def recipients(self) -> list[str]:
        """
        Return a list of all recipients of the email (includes direct
        addressees as well as Cc and Bcc entries).
        """
        return [email for email in (self.to + self.cc + self.bcc) if email]

    def send(self, fail_silently: bool = False) -> int:
        """Send the email message."""
        if not self.recipients():
            # Don't bother creating the network connection if there's nobody to
            # send to.
            return 0
        return self.get_connection(fail_silently).send_messages([self])

    def attach(
        self,
        filename: MIMEBase | str | None = None,
        content: str | bytes | None = None,
        mimetype: str | None = None,
    ) -> None:
        """
        Attach a file with the given filename and content. The filename can
        be omitted and the mimetype is guessed, if not provided.

        If the first parameter is a MIMEBase subclass, insert it directly
        into the resulting message attachments.

        For a text/* mimetype (guessed or specified), when a bytes object is
        specified as content, decode it as UTF-8. If that fails, set the
        mimetype to DEFAULT_ATTACHMENT_MIME_TYPE and don't decode the content.
        """
        if isinstance(filename, MIMEBase):
            if content is not None or mimetype is not None:
                raise ValueError(
                    "content and mimetype must not be given when a MIMEBase "
                    "instance is provided."
                )
            self.attachments.append(filename)
        elif content is None:
            raise ValueError("content must be provided.")
        else:
            mimetype = (
                mimetype
                or mimetypes.guess_type(filename)[0]
                or DEFAULT_ATTACHMENT_MIME_TYPE
            )
            basetype, subtype = mimetype.split("/", 1)

            if basetype == "text":
                if isinstance(content, bytes):
                    try:
                        content = content.decode()
                    except UnicodeDecodeError:
                        # If mimetype suggests the file is text but it's
                        # actually binary, read() raises a UnicodeDecodeError.
                        mimetype = DEFAULT_ATTACHMENT_MIME_TYPE

            self.attachments.append((filename, content, mimetype))

    def attach_file(
        self, path: str | PathLike[str], mimetype: str | None = None
    ) -> None:
        """
        Attach a file from the filesystem.

        Set the mimetype to DEFAULT_ATTACHMENT_MIME_TYPE if it isn't specified
        and cannot be guessed.

        For a text/* mimetype (guessed or specified), decode the file's content
        as UTF-8. If that fails, set the mimetype to
        DEFAULT_ATTACHMENT_MIME_TYPE and don't decode the content.
        """
        path = Path(path)
        with path.open("rb") as file:
            content = file.read()
            self.attach(path.name, content, mimetype)

    def _create_message(self, msg: SafeMIMEText) -> SafeMIMEText | SafeMIMEMultipart:
        return self._create_attachments(msg)

    def _create_attachments(
        self, msg: SafeMIMEText | SafeMIMEMultipart
    ) -> SafeMIMEText | SafeMIMEMultipart:
        if self.attachments:
            encoding = self.encoding or settings.DEFAULT_CHARSET
            body_msg = msg
            msg = SafeMIMEMultipart(_subtype=self.mixed_subtype, encoding=encoding)
            if self.body or body_msg.is_multipart():
                msg.attach(body_msg)
            for attachment in self.attachments:
                if isinstance(attachment, MIMEBase):
                    msg.attach(attachment)
                else:
                    msg.attach(self._create_attachment(*attachment))
        return msg

    def _create_mime_attachment(
        self, content: str | bytes | EmailMessage | Message, mimetype: str
    ) -> SafeMIMEText | SafeMIMEMessage | MIMEBase:
        """
        Convert the content, mimetype pair into a MIME attachment object.

        If the mimetype is message/rfc822, content may be an
        email.Message or EmailMessage object, as well as a str.
        """
        basetype, subtype = mimetype.split("/", 1)
        if basetype == "text":
            encoding = self.encoding or settings.DEFAULT_CHARSET
            if not isinstance(content, str):
                content = force_str(content)
            attachment = SafeMIMEText(content, subtype, encoding)
        elif basetype == "message" and subtype == "rfc822":
            # Bug #18967: Per RFC 2046 Section 5.2.1, message/rfc822
            # attachments must not be base64 encoded.
            if isinstance(content, EmailMessage):
                # convert content into an email.Message first
                content = content.message()
            elif not isinstance(content, Message):
                # For compatibility with existing code, parse the message
                # into an email.Message object if it is not one already.
                content = message_from_string(force_str(content))

            attachment = SafeMIMEMessage(content, subtype)
        else:
            # Encode non-text attachments with base64.
            attachment = MIMEBase(basetype, subtype)
            attachment.set_payload(content)
            Encoders.encode_base64(attachment)
        return attachment

    def _create_attachment(
        self, filename: str | None, content: str | bytes, mimetype: str | None = None
    ) -> SafeMIMEText | SafeMIMEMessage | MIMEBase:
        """
        Convert the filename, content, mimetype triple into a MIME attachment
        object.
        """
        attachment = self._create_mime_attachment(content, mimetype)
        if filename:
            try:
                filename.encode("ascii")
                encoded_filename: str | tuple[str, str, str] = filename
            except UnicodeEncodeError:
                encoded_filename = ("utf-8", "", filename)
            attachment.add_header(
                "Content-Disposition", "attachment", filename=encoded_filename
            )
        return attachment

    def _set_list_header_if_not_empty(
        self,
        msg: SafeMIMEText | SafeMIMEMultipart,
        header: str,
        values: list[str],
    ) -> None:
        """
        Set msg's header, either from self.extra_headers, if present, or from
        the values argument.
        """
        if values:
            try:
                value = self.extra_headers[header]
            except KeyError:
                value = ", ".join(str(v) for v in values)
            msg[header] = value


class EmailMultiAlternatives(EmailMessage):
    """
    A version of EmailMessage that makes it easy to send multipart/alternative
    messages. For example, including text and HTML versions of the text is
    made easier.
    """

    alternative_subtype = "alternative"

    def __init__(
        self,
        subject: str = "",
        body: str = "",
        from_email: str | None = None,
        to: list[str] | tuple[str, ...] | None = None,
        bcc: list[str] | tuple[str, ...] | None = None,
        connection: BaseEmailBackend | None = None,
        attachments: list[MIMEBase | tuple[str, str, str]] | None = None,
        headers: dict[str, str] | None = None,
        alternatives: list[tuple[str, str]] | None = None,
        cc: list[str] | tuple[str, ...] | None = None,
        reply_to: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        """
        Initialize a single email message (which can be sent to multiple
        recipients).
        """
        super().__init__(
            subject,
            body,
            from_email,
            to,
            bcc,
            connection,
            attachments,
            headers,
            cc,
            reply_to,
        )
        self.alternatives = alternatives or []

    def attach_alternative(self, content: str, mimetype: str) -> None:
        """Attach an alternative content representation."""
        if content is None or mimetype is None:
            raise ValueError("Both content and mimetype must be provided.")
        self.alternatives.append((content, mimetype))

    def _create_message(self, msg: SafeMIMEText) -> SafeMIMEText | SafeMIMEMultipart:
        return self._create_attachments(self._create_alternatives(msg))

    def _create_alternatives(
        self, msg: SafeMIMEText | SafeMIMEMultipart
    ) -> SafeMIMEText | SafeMIMEMultipart:
        encoding = self.encoding or settings.DEFAULT_CHARSET
        if self.alternatives:
            body_msg = msg
            msg = SafeMIMEMultipart(
                _subtype=self.alternative_subtype, encoding=encoding
            )
            if self.body:
                msg.attach(body_msg)
            for alternative in self.alternatives:
                msg.attach(self._create_mime_attachment(*alternative))
        return msg


class TemplateEmail(EmailMultiAlternatives):
    def __init__(
        self,
        *,
        template: str,
        context: dict[str, Any] | None = None,
        subject: str = "",
        from_email: str | None = None,
        to: list[str] | tuple[str, ...] | None = None,
        bcc: list[str] | tuple[str, ...] | None = None,
        connection: BaseEmailBackend | None = None,
        attachments: list[MIMEBase | tuple[str, str, str]] | None = None,
        headers: dict[str, str] | None = None,
        alternatives: list[tuple[str, str]] | None = None,
        cc: list[str] | tuple[str, ...] | None = None,
        reply_to: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.template = template
        self.context = context or {}

        # Run this once for all uses of the context
        render_context = self.get_template_context()

        self.body_html, body = self.render_content(render_context)

        if not subject:
            subject = self.render_subject(render_context)

        super().__init__(
            subject=subject,
            body=body,
            from_email=from_email,
            to=to,
            bcc=bcc,
            connection=connection,
            attachments=attachments,
            headers=headers,
            alternatives=alternatives,
            cc=cc,
            reply_to=reply_to,
        )

        self.attach_alternative(self.body_html, "text/html")

    def get_template_context(self) -> dict[str, Any]:
        """Subclasses can override this method to add context data."""
        return self.context

    def render_content(self, context: dict[str, Any]) -> tuple[str, str]:
        html_content = self.render_html(context)

        try:
            plain_content = self.render_plain(context)
        except TemplateFileMissing:
            plain_content = strip_tags(html_content)

        return html_content, plain_content

    def render_plain(self, context: dict[str, Any]) -> str:
        return Template(self.get_plain_template_name()).render(context)

    def render_html(self, context: dict[str, Any]) -> str:
        return Template(self.get_html_template_name()).render(context)

    def render_subject(self, context: dict[str, Any]) -> str:
        try:
            subject = Template(self.get_subject_template_name()).render(context)
            return subject.strip()
        except TemplateFileMissing:
            return ""

    def get_plain_template_name(self) -> str:
        return f"email/{self.template}.txt"

    def get_html_template_name(self) -> str:
        return f"email/{self.template}.html"

    def get_subject_template_name(self) -> str:
        return f"email/{self.template}.subject.txt"

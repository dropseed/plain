import datetime
import io
import json
import mimetypes
import os
import re
import sys
import time
from email.header import Header
from functools import cached_property
from http.client import responses
from http.cookies import SimpleCookie

from plain import signals
from plain.http.cookie import sign_cookie_value
from plain.json import PlainJSONEncoder
from plain.runtime import settings
from plain.utils import timezone
from plain.utils.datastructures import CaseInsensitiveMapping
from plain.utils.encoding import iri_to_uri
from plain.utils.http import content_disposition_header, http_date
from plain.utils.regex_helper import _lazy_re_compile

_charset_from_content_type_re = _lazy_re_compile(
    r";\s*charset=(?P<charset>[^\s;]+)", re.I
)


class ResponseHeaders(CaseInsensitiveMapping):
    def __init__(self, data):
        """
        Populate the initial data using __setitem__ to ensure values are
        correctly encoded.
        """
        self._store = {}
        if data:
            for header, value in self._unpack_items(data):
                self[header] = value

    def _convert_to_charset(self, value, charset, mime_encode=False):
        """
        Convert headers key/value to ascii/latin-1 native strings.
        `charset` must be 'ascii' or 'latin-1'. If `mime_encode` is True and
        `value` can't be represented in the given charset, apply MIME-encoding.
        """
        try:
            if isinstance(value, str):
                # Ensure string is valid in given charset
                value.encode(charset)
            elif isinstance(value, bytes):
                # Convert bytestring using given charset
                value = value.decode(charset)
            else:
                value = str(value)
                # Ensure string is valid in given charset.
                value.encode(charset)
            if "\n" in value or "\r" in value:
                raise BadHeaderError(
                    f"Header values can't contain newlines (got {value!r})"
                )
        except UnicodeError as e:
            # Encoding to a string of the specified charset failed, but we
            # don't know what type that value was, or if it contains newlines,
            # which we may need to check for before sending it to be
            # encoded for multiple character sets.
            if (isinstance(value, bytes) and (b"\n" in value or b"\r" in value)) or (
                isinstance(value, str) and ("\n" in value or "\r" in value)
            ):
                raise BadHeaderError(
                    f"Header values can't contain newlines (got {value!r})"
                ) from e
            if mime_encode:
                value = Header(value, "utf-8", maxlinelen=sys.maxsize).encode()
            else:
                e.reason += f", HTTP response headers must be in {charset} format"
                raise
        return value

    def __delitem__(self, key):
        self.pop(key)

    def __setitem__(self, key, value):
        key = self._convert_to_charset(key, "ascii")
        value = self._convert_to_charset(value, "latin-1", mime_encode=True)
        self._store[key.lower()] = (key, value)

    def pop(self, key, default=None):
        return self._store.pop(key.lower(), default)

    def setdefault(self, key, value):
        if key not in self:
            self[key] = value


class BadHeaderError(ValueError):
    pass


class ResponseBase:
    """
    An HTTP response base class with dictionary-accessed headers.

    This class doesn't handle content. It should not be used directly.
    Use the Response and StreamingResponse subclasses instead.
    """

    status_code = 200

    def __init__(
        self,
        *,
        content_type=None,
        status_code=None,
        reason=None,
        charset=None,
        headers=None,
    ):
        self.headers = ResponseHeaders(headers)
        self._charset = charset
        if "Content-Type" not in self.headers:
            if content_type is None:
                content_type = f"text/html; charset={self.charset}"
            self.headers["Content-Type"] = content_type
        elif content_type:
            raise ValueError(
                "'headers' must not contain 'Content-Type' when the "
                "'content_type' parameter is provided."
            )
        self._resource_closers = []
        # This parameter is set by the handler. It's necessary to preserve the
        # historical behavior of request_finished.
        self._handler_class = None
        self.cookies = SimpleCookie()
        self.closed = False
        if status_code is not None:
            try:
                self.status_code = int(status_code)
            except (ValueError, TypeError):
                raise TypeError("HTTP status code must be an integer.")

            if not 100 <= self.status_code <= 599:
                raise ValueError("HTTP status code must be an integer from 100 to 599.")
        self._reason_phrase = reason

    @property
    def reason_phrase(self):
        if self._reason_phrase is not None:
            return self._reason_phrase
        # Leave self._reason_phrase unset in order to use the default
        # reason phrase for status code.
        return responses.get(self.status_code, "Unknown Status Code")

    @reason_phrase.setter
    def reason_phrase(self, value):
        self._reason_phrase = value

    @property
    def charset(self):
        if self._charset is not None:
            return self._charset
        # The Content-Type header may not yet be set, because the charset is
        # being inserted *into* it.
        if content_type := self.headers.get("Content-Type"):
            if matched := _charset_from_content_type_re.search(content_type):
                # Extract the charset and strip its double quotes.
                # Note that having parsed it from the Content-Type, we don't
                # store it back into the _charset for later intentionally, to
                # allow for the Content-Type to be switched again later.
                return matched["charset"].replace('"', "")
        return settings.DEFAULT_CHARSET

    @charset.setter
    def charset(self, value):
        self._charset = value

    def serialize_headers(self):
        """HTTP headers as a bytestring."""
        return b"\r\n".join(
            [
                key.encode("ascii") + b": " + value.encode("latin-1")
                for key, value in self.headers.items()
            ]
        )

    __bytes__ = serialize_headers

    @property
    def _content_type_for_repr(self):
        return (
            ', "{}"'.format(self.headers["Content-Type"])
            if "Content-Type" in self.headers
            else ""
        )

    def set_cookie(
        self,
        key,
        value="",
        max_age=None,
        expires=None,
        path="/",
        domain=None,
        secure=False,
        httponly=False,
        samesite=None,
    ):
        """
        Set a cookie.

        ``expires`` can be:
        - a string in the correct format,
        - a naive ``datetime.datetime`` object in UTC,
        - an aware ``datetime.datetime`` object in any time zone.
        If it is a ``datetime.datetime`` object then calculate ``max_age``.

        ``max_age`` can be:
        - int/float specifying seconds,
        - ``datetime.timedelta`` object.
        """
        self.cookies[key] = value
        if expires is not None:
            if isinstance(expires, datetime.datetime):
                if timezone.is_naive(expires):
                    expires = timezone.make_aware(expires, datetime.UTC)
                delta = expires - datetime.datetime.now(tz=datetime.UTC)
                # Add one second so the date matches exactly (a fraction of
                # time gets lost between converting to a timedelta and
                # then the date string).
                delta += datetime.timedelta(seconds=1)
                # Just set max_age - the max_age logic will set expires.
                expires = None
                if max_age is not None:
                    raise ValueError("'expires' and 'max_age' can't be used together.")
                max_age = max(0, delta.days * 86400 + delta.seconds)
            else:
                self.cookies[key]["expires"] = expires
        else:
            self.cookies[key]["expires"] = ""
        if max_age is not None:
            if isinstance(max_age, datetime.timedelta):
                max_age = max_age.total_seconds()
            self.cookies[key]["max-age"] = int(max_age)
            # IE requires expires, so set it if hasn't been already.
            if not expires:
                self.cookies[key]["expires"] = http_date(time.time() + max_age)
        if path is not None:
            self.cookies[key]["path"] = path
        if domain is not None:
            self.cookies[key]["domain"] = domain
        if secure:
            self.cookies[key]["secure"] = True
        if httponly:
            self.cookies[key]["httponly"] = True
        if samesite:
            if samesite.lower() not in ("lax", "none", "strict"):
                raise ValueError('samesite must be "lax", "none", or "strict".')
            self.cookies[key]["samesite"] = samesite

    def set_signed_cookie(self, key, value, salt="", **kwargs):
        """Set a cookie signed with the SECRET_KEY."""

        signed_value = sign_cookie_value(key, value, salt)
        return self.set_cookie(key, signed_value, **kwargs)

    def delete_cookie(self, key, path="/", domain=None, samesite=None):
        # Browsers can ignore the Set-Cookie header if the cookie doesn't use
        # the secure flag and:
        # - the cookie name starts with "__Host-" or "__Secure-", or
        # - the samesite is "none".
        secure = key.startswith(("__Secure-", "__Host-")) or (
            samesite and samesite.lower() == "none"
        )
        self.set_cookie(
            key,
            max_age=0,
            path=path,
            domain=domain,
            secure=secure,
            expires="Thu, 01 Jan 1970 00:00:00 GMT",
            samesite=samesite,
        )

    # Common methods used by subclasses

    def make_bytes(self, value):
        """Turn a value into a bytestring encoded in the output charset."""
        # Per PEP 3333, this response body must be bytes. To avoid returning
        # an instance of a subclass, this function returns `bytes(value)`.
        # This doesn't make a copy when `value` already contains bytes.

        # Handle string types -- we can't rely on force_bytes here because:
        # - Python attempts str conversion first
        # - when self._charset != 'utf-8' it re-encodes the content
        if isinstance(value, bytes | memoryview):
            return bytes(value)
        if isinstance(value, str):
            return bytes(value.encode(self.charset))
        # Handle non-string types.
        return str(value).encode(self.charset)

    # These methods partially implement the file-like object interface.
    # See https://docs.python.org/library/io.html#io.IOBase

    # The WSGI server must call this method upon completion of the request.
    # See http://blog.dscpl.com.au/2012/10/obligations-for-calling-close-on.html
    def close(self):
        for closer in self._resource_closers:
            try:
                closer()
            except Exception:
                pass
        # Free resources that were still referenced.
        self._resource_closers.clear()
        self.closed = True
        signals.request_finished.send(sender=self._handler_class)

    def write(self, content):
        raise OSError(f"This {self.__class__.__name__} instance is not writable")

    def flush(self):
        pass

    def tell(self):
        raise OSError(
            f"This {self.__class__.__name__} instance cannot tell its position"
        )

    # These methods partially implement a stream-like object interface.
    # See https://docs.python.org/library/io.html#io.IOBase

    def readable(self):
        return False

    def seekable(self):
        return False

    def writable(self):
        return False

    def writelines(self, lines):
        raise OSError(f"This {self.__class__.__name__} instance is not writable")


class Response(ResponseBase):
    """
    An HTTP response class with a string as content.

    This content can be read, appended to, or replaced.
    """

    streaming = False
    non_picklable_attrs = frozenset(
        [
            "resolver_match",
            # Non-picklable attributes added by test clients.
            "client",
            "context",
            "json",
            "templates",
        ]
    )

    def __init__(self, content=b"", **kwargs):
        super().__init__(**kwargs)
        # Content is a bytestring. See the `content` property methods.
        self.content = content

    def __getstate__(self):
        obj_dict = self.__dict__.copy()
        for attr in self.non_picklable_attrs:
            if attr in obj_dict:
                del obj_dict[attr]
        return obj_dict

    def __repr__(self):
        return "<%(cls)s status_code=%(status_code)d%(content_type)s>" % {  # noqa: UP031
            "cls": self.__class__.__name__,
            "status_code": self.status_code,
            "content_type": self._content_type_for_repr,
        }

    def serialize(self):
        """Full HTTP message, including headers, as a bytestring."""
        return self.serialize_headers() + b"\r\n\r\n" + self.content

    __bytes__ = serialize

    @property
    def content(self):
        return b"".join(self._container)

    @content.setter
    def content(self, value):
        # Consume iterators upon assignment to allow repeated iteration.
        if hasattr(value, "__iter__") and not isinstance(
            value, bytes | memoryview | str
        ):
            content = b"".join(self.make_bytes(chunk) for chunk in value)
            if hasattr(value, "close"):
                try:
                    value.close()
                except Exception:
                    pass
        else:
            content = self.make_bytes(value)
        # Create a list of properly encoded bytestrings to support write().
        self._container = [content]

    @cached_property
    def text(self):
        return self.content.decode(self.charset or "utf-8")

    def __iter__(self):
        return iter(self._container)

    def write(self, content):
        self._container.append(self.make_bytes(content))

    def tell(self):
        return len(self.content)

    def getvalue(self):
        return self.content

    def writable(self):
        return True

    def writelines(self, lines):
        for line in lines:
            self.write(line)


class StreamingResponse(ResponseBase):
    """
    A streaming HTTP response class with an iterator as content.

    This should only be iterated once, when the response is streamed to the
    client. However, it can be appended to or replaced with a new iterator
    that wraps the original content (or yields entirely new content).
    """

    streaming = True

    def __init__(self, streaming_content=(), **kwargs):
        super().__init__(**kwargs)
        # `streaming_content` should be an iterable of bytestrings.
        # See the `streaming_content` property methods.
        self.streaming_content = streaming_content

    def __repr__(self):
        return "<%(cls)s status_code=%(status_code)d%(content_type)s>" % {  # noqa: UP031
            "cls": self.__class__.__qualname__,
            "status_code": self.status_code,
            "content_type": self._content_type_for_repr,
        }

    @property
    def content(self):
        raise AttributeError(
            f"This {self.__class__.__name__} instance has no `content` attribute. Use "
            "`streaming_content` instead."
        )

    @property
    def streaming_content(self):
        return map(self.make_bytes, self._iterator)

    @streaming_content.setter
    def streaming_content(self, value):
        self._set_streaming_content(value)

    def _set_streaming_content(self, value):
        # Ensure we can never iterate on "value" more than once.
        self._iterator = iter(value)
        if hasattr(value, "close"):
            self._resource_closers.append(value.close)

    def __iter__(self):
        return iter(self.streaming_content)

    def getvalue(self):
        return b"".join(self.streaming_content)


class FileResponse(StreamingResponse):
    """
    A streaming HTTP response class optimized for files.
    """

    block_size = 4096

    def __init__(self, *args, as_attachment=False, filename="", **kwargs):
        self.as_attachment = as_attachment
        self.filename = filename
        self._no_explicit_content_type = (
            "content_type" not in kwargs or kwargs["content_type"] is None
        )
        super().__init__(*args, **kwargs)

    def _set_streaming_content(self, value):
        if not hasattr(value, "read"):
            self.file_to_stream = None
            return super()._set_streaming_content(value)

        self.file_to_stream = filelike = value
        if hasattr(filelike, "close"):
            self._resource_closers.append(filelike.close)
        value = iter(lambda: filelike.read(self.block_size), b"")
        self.set_headers(filelike)
        super()._set_streaming_content(value)

    def set_headers(self, filelike):
        """
        Set some common response headers (Content-Length, Content-Type, and
        Content-Disposition) based on the `filelike` response content.
        """
        filename = getattr(filelike, "name", "")
        filename = filename if isinstance(filename, str) else ""
        seekable = hasattr(filelike, "seek") and (
            not hasattr(filelike, "seekable") or filelike.seekable()
        )
        if hasattr(filelike, "tell"):
            if seekable:
                initial_position = filelike.tell()
                filelike.seek(0, io.SEEK_END)
                self.headers["Content-Length"] = filelike.tell() - initial_position
                filelike.seek(initial_position)
            elif hasattr(filelike, "getbuffer"):
                self.headers["Content-Length"] = (
                    filelike.getbuffer().nbytes - filelike.tell()
                )
            elif os.path.exists(filename):
                self.headers["Content-Length"] = (
                    os.path.getsize(filename) - filelike.tell()
                )
        elif seekable:
            self.headers["Content-Length"] = sum(
                iter(lambda: len(filelike.read(self.block_size)), 0)
            )
            filelike.seek(-int(self.headers["Content-Length"]), io.SEEK_END)

        filename = os.path.basename(self.filename or filename)
        if self._no_explicit_content_type:
            if filename:
                content_type, encoding = mimetypes.guess_type(filename)
                # Encoding isn't set to prevent browsers from automatically
                # uncompressing files.
                content_type = {
                    "br": "application/x-brotli",
                    "bzip2": "application/x-bzip",
                    "compress": "application/x-compress",
                    "gzip": "application/gzip",
                    "xz": "application/x-xz",
                }.get(encoding, content_type)
                self.headers["Content-Type"] = (
                    content_type or "application/octet-stream"
                )
            else:
                self.headers["Content-Type"] = "application/octet-stream"

        if content_disposition := content_disposition_header(
            self.as_attachment, filename
        ):
            self.headers["Content-Disposition"] = content_disposition


class ResponseRedirect(Response):
    """HTTP redirect response"""

    status_code = 302

    def __init__(self, redirect_to, **kwargs):
        super().__init__(**kwargs)
        self.headers["Location"] = iri_to_uri(redirect_to)

    @property
    def url(self):
        return self.headers["Location"]

    def __repr__(self):
        return (
            '<%(cls)s status_code=%(status_code)d%(content_type)s, url="%(url)s">'  # noqa: UP031
            % {
                "cls": self.__class__.__name__,
                "status_code": self.status_code,
                "content_type": self._content_type_for_repr,
                "url": self.url,
            }
        )


class ResponseNotModified(Response):
    """HTTP 304 response"""

    status_code = 304

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.headers["content-type"]

    @Response.content.setter
    def content(self, value):
        if value:
            raise AttributeError(
                "You cannot set content to a 304 (Not Modified) response"
            )
        self._container = []


class ResponseBadRequest(Response):
    """HTTP 400 response"""

    status_code = 400


class ResponseNotFound(Response):
    """HTTP 404 response"""

    status_code = 404


class ResponseForbidden(Response):
    """HTTP 403 response"""

    status_code = 403


class ResponseNotAllowed(Response):
    """HTTP 405 response"""

    status_code = 405

    def __init__(self, permitted_methods, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.headers["Allow"] = ", ".join(permitted_methods)

    def __repr__(self):
        return "<%(cls)s [%(methods)s] status_code=%(status_code)d%(content_type)s>" % {  # noqa: UP031
            "cls": self.__class__.__name__,
            "status_code": self.status_code,
            "content_type": self._content_type_for_repr,
            "methods": self.headers["Allow"],
        }


class ResponseGone(Response):
    """HTTP 410 response"""

    status_code = 410


class ResponseServerError(Response):
    """HTTP 500 response"""

    status_code = 500


class Http404(Exception):
    pass


class JsonResponse(Response):
    """
    An HTTP response class that consumes data to be serialized to JSON.

    :param data: Data to be dumped into json. By default only ``dict`` objects
      are allowed to be passed due to a security flaw before ECMAScript 5. See
      the ``safe`` parameter for more information.
    :param encoder: Should be a json encoder class. Defaults to
      ``plain.json.PlainJSONEncoder``.
    :param safe: Controls if only ``dict`` objects may be serialized. Defaults
      to ``True``.
    :param json_dumps_params: A dictionary of kwargs passed to json.dumps().
    """

    def __init__(
        self,
        data,
        encoder=PlainJSONEncoder,
        safe=True,
        json_dumps_params=None,
        **kwargs,
    ):
        if safe and not isinstance(data, dict):
            raise TypeError(
                "In order to allow non-dict objects to be serialized set the "
                "safe parameter to False."
            )
        if json_dumps_params is None:
            json_dumps_params = {}
        kwargs.setdefault("content_type", "application/json")
        data = json.dumps(data, cls=encoder, **json_dumps_params)
        super().__init__(content=data, **kwargs)

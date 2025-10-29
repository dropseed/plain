from __future__ import annotations

import codecs
import copy
import json
import secrets
import uuid
from collections.abc import Iterator
from functools import cached_property
from io import BytesIO
from itertools import chain
from typing import IO, Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit

from plain.exceptions import (
    ImproperlyConfigured,
    RequestDataTooBig,
    TooManyFieldsSent,
)
from plain.http.cookie import unsign_cookie_value
from plain.http.multipartparser import (
    MultiPartParser,
    MultiPartParserError,
    TooManyFilesSent,
)
from plain.internal.files import uploadhandler
from plain.runtime import settings
from plain.utils.datastructures import (
    CaseInsensitiveMapping,
    ImmutableList,
    MultiValueDict,
)
from plain.utils.encoding import iri_to_uri
from plain.utils.http import parse_header_parameters


class UnreadablePostError(OSError):
    pass


class RawPostDataException(Exception):
    """
    You cannot access raw_post_data from a request that has
    multipart/* POST data if it has been accessed via POST,
    FILES, etc..
    """

    pass


class Request:
    """A basic HTTP request."""

    # The encoding used in GET/POST dicts. None means use default setting.
    _encoding = None
    _upload_handlers = []

    non_picklable_attrs = frozenset(["resolver_match", "_stream"])

    def __init__(self):
        # WARNING: The `WSGIRequest` subclass doesn't call `super`.
        # Any variable assignment made here should also happen in
        # `WSGIRequest.__init__()`.

        # A unique ID we can use to trace this request
        self.unique_id = str(uuid.uuid4())

        self.query_params = QueryDict(mutable=True)
        self.data = QueryDict(mutable=True)
        self.cookies = {}
        self.meta = {}
        self.files = MultiValueDict()

        self.path = ""
        self.path_info = ""
        self.method = None
        self.resolver_match = None
        self.content_type = None
        self.content_params = None

    def __repr__(self) -> str:
        if self.method is None or not self.get_full_path():
            return f"<{self.__class__.__name__}>"
        return f"<{self.__class__.__name__}: {self.method} {self.get_full_path()!r}>"

    def __getstate__(self) -> dict[str, Any]:
        obj_dict = self.__dict__.copy()
        for attr in self.non_picklable_attrs:
            if attr in obj_dict:
                del obj_dict[attr]
        return obj_dict

    def __deepcopy__(self, memo: dict[int, Any]) -> Request:
        obj = copy.copy(self)
        for attr in self.non_picklable_attrs:
            if hasattr(self, attr):
                setattr(obj, attr, copy.deepcopy(getattr(self, attr), memo))
        memo[id(self)] = obj
        return obj

    @cached_property
    def headers(self) -> RequestHeaders:
        return RequestHeaders(self.meta)

    @cached_property
    def csp_nonce(self) -> str:
        """Generate a cryptographically secure nonce for Content Security Policy.

        The nonce is generated once per request and cached. It can be used in
        CSP headers and templates to allow specific inline scripts/styles while
        blocking others.
        """
        return secrets.token_urlsafe(16)

    @cached_property
    def accepted_types(self) -> list[MediaType]:
        """Return accepted media types sorted by quality value (highest first).

        When quality values are equal, the original order from the Accept header
        is preserved (as per HTTP spec).
        """
        header = self.headers.get("Accept", "*/*")
        types = [MediaType(token) for token in header.split(",") if token.strip()]
        return sorted(types, key=lambda t: t.quality, reverse=True)

    def get_preferred_type(self, *media_types: str) -> str | None:
        """Return the most preferred media type from the given options.

        Checks the Accept header in priority order (by quality value) and returns
        the first matching media type from the provided options.

        Returns None if none of the options are accepted.

        Example:
            # Accept: text/html;q=1.0, application/json;q=0.5
            request.get_preferred_type("application/json", "text/html")  # Returns "text/html"
        """
        for accepted in self.accepted_types:
            for option in media_types:
                if accepted.match(option):
                    return option
        return None

    def accepts(self, media_type: str) -> bool:
        """Check if the given media type is accepted."""
        return self.get_preferred_type(media_type) is not None

    def _set_content_type_params(self, meta: dict[str, Any]) -> None:
        """Set content_type, content_params, and encoding."""
        self.content_type, self.content_params = parse_header_parameters(
            meta.get("CONTENT_TYPE", "")
        )
        if "charset" in self.content_params:
            try:
                codecs.lookup(self.content_params["charset"])
            except LookupError:
                pass
            else:
                self.encoding = self.content_params["charset"]

    @cached_property
    def host(self) -> str:
        """
        Return the HTTP host using the environment or request headers.

        Host validation is performed by HostValidationMiddleware, so this
        property can safely return the host without any validation.
        """
        # We try three options, in order of decreasing preference.
        if settings.USE_X_FORWARDED_HOST and ("HTTP_X_FORWARDED_HOST" in self.meta):
            host = self.meta["HTTP_X_FORWARDED_HOST"]
        elif "HTTP_HOST" in self.meta:
            host = self.meta["HTTP_HOST"]
        else:
            # Reconstruct the host using the algorithm from PEP 333.
            host = self.meta["SERVER_NAME"]
            server_port = self.port
            if server_port != ("443" if self.is_https() else "80"):
                host = f"{host}:{server_port}"
        return host

    @cached_property
    def port(self) -> str:
        """Return the port number for the request as a string."""
        if settings.USE_X_FORWARDED_PORT and "HTTP_X_FORWARDED_PORT" in self.meta:
            port = self.meta["HTTP_X_FORWARDED_PORT"]
        else:
            port = self.meta["SERVER_PORT"]
        return str(port)

    def get_full_path(self, force_append_slash: bool = False) -> str:
        """
        Return the full path for the request, including query string.

        If force_append_slash is True, append a trailing slash if the path
        doesn't already end with one.
        """
        # RFC 3986 requires query string arguments to be in the ASCII range.
        # Rather than crash if this doesn't happen, we encode defensively.

        def escape_uri_path(path: str) -> str:
            """
            Escape the unsafe characters from the path portion of a Uniform Resource
            Identifier (URI).
            """
            # These are the "reserved" and "unreserved" characters specified in RFC
            # 3986 Sections 2.2 and 2.3:
            #   reserved    = ";" | "/" | "?" | ":" | "@" | "&" | "=" | "+" | "$" | ","
            #   unreserved  = alphanum | mark
            #   mark        = "-" | "_" | "." | "!" | "~" | "*" | "'" | "(" | ")"
            # The list of safe characters here is constructed subtracting ";", "=",
            # and "?" according to RFC 3986 Section 3.3.
            # The reason for not subtracting and escaping "/" is that we are escaping
            # the entire path, not a path segment.
            return quote(path, safe="/:@&+$,-_.!~*'()")

        query_string = self.meta.get("QUERY_STRING", "")
        return "{}{}{}".format(
            escape_uri_path(self.path),
            "/" if force_append_slash and not self.path.endswith("/") else "",
            ("?" + (iri_to_uri(query_string) or "")) if query_string else "",
        )

    def build_absolute_uri(self, location: str | None = None) -> str:
        """
        Build an absolute URI from the location and the variables available in
        this request. If no ``location`` is specified, build the absolute URI
        using request.get_full_path(). If the location is absolute, convert it
        to an RFC 3987 compliant URI and return it. If location is relative or
        is scheme-relative (i.e., ``//example.com/``), urljoin() it to a base
        URL constructed from the request variables.
        """
        if location is None:
            # Make it an absolute url (but schemeless and domainless) for the
            # edge case that the path starts with '//'.
            location = f"//{self.get_full_path()}"
        else:
            # Coerce lazy locations.
            location = str(location)
        bits = urlsplit(location)
        if not (bits.scheme and bits.netloc):
            current_scheme_host = f"{self.scheme}://{self.host}"

            # Handle the simple, most common case. If the location is absolute
            # and a scheme or host (netloc) isn't provided, skip an expensive
            # urljoin() as long as no path segments are '.' or '..'.
            if (
                bits.path.startswith("/")
                and not bits.scheme
                and not bits.netloc
                and "/./" not in bits.path
                and "/../" not in bits.path
            ):
                # If location starts with '//' but has no netloc, reuse the
                # schema and netloc from the current request. Strip the double
                # slashes and continue as if it wasn't specified.
                location = current_scheme_host + location.removeprefix("//")
            else:
                # Join the constructed URL with the provided location, which
                # allows the provided location to apply query strings to the
                # base path.
                location = urljoin(current_scheme_host + self.path, location)

        return iri_to_uri(location) or ""

    def _get_scheme(self) -> str:
        """
        Hook for subclasses like WSGIRequest to implement. Return 'http' by
        default.
        """
        return "http"

    @property
    def scheme(self) -> str:
        if settings.HTTPS_PROXY_HEADER:
            try:
                header, secure_value = settings.HTTPS_PROXY_HEADER
            except ValueError:
                raise ImproperlyConfigured(
                    "The HTTPS_PROXY_HEADER setting must be a tuple containing "
                    "two values."
                )
            header_value = self.meta.get(header)
            if header_value is not None:
                header_value, *_ = header_value.split(",", 1)
                return "https" if header_value.strip() == secure_value else "http"
        return self._get_scheme()

    def is_https(self) -> bool:
        return self.scheme == "https"

    @property
    def encoding(self) -> str | None:
        return self._encoding

    @encoding.setter
    def encoding(self, val: str) -> None:
        """
        Set the encoding used for query_params/data accesses. If the query_params or data
        dictionary has already been created, remove and recreate it on the
        next access (so that it is decoded correctly).
        """
        self._encoding = val
        if hasattr(self, "query_params"):
            del self.query_params
        if hasattr(self, "_data"):
            del self._data

    def _initialize_handlers(self) -> None:
        self._upload_handlers = [
            uploadhandler.load_handler(handler, self)
            for handler in settings.FILE_UPLOAD_HANDLERS
        ]

    @property
    def upload_handlers(self) -> list[Any]:
        if not self._upload_handlers:
            # If there are no upload handlers defined, initialize them from settings.
            self._initialize_handlers()
        return self._upload_handlers

    @upload_handlers.setter
    def upload_handlers(self, upload_handlers: list[Any]) -> None:
        if hasattr(self, "_files"):
            raise AttributeError(
                "You cannot set the upload handlers after the upload has been "
                "processed."
            )
        self._upload_handlers = upload_handlers

    def parse_file_upload(
        self, meta: dict[str, Any], post_data: IO[bytes]
    ) -> tuple[Any, MultiValueDict]:
        """Return a tuple of (data QueryDict, files MultiValueDict)."""
        self.upload_handlers = ImmutableList(
            self.upload_handlers,
            warning=(
                "You cannot alter upload handlers after the upload has been processed."
            ),
        )
        parser = MultiPartParser(meta, post_data, self.upload_handlers, self.encoding)
        return parser.parse()

    @property
    def body(self) -> bytes:
        if not hasattr(self, "_body"):
            if self._read_started:
                raise RawPostDataException(
                    "You cannot access body after reading from request's data stream"
                )

            # Limit the maximum request data size that will be handled in-memory.
            if (
                settings.DATA_UPLOAD_MAX_MEMORY_SIZE is not None
                and int(self.meta.get("CONTENT_LENGTH") or 0)
                > settings.DATA_UPLOAD_MAX_MEMORY_SIZE
            ):
                raise RequestDataTooBig(
                    "Request body exceeded settings.DATA_UPLOAD_MAX_MEMORY_SIZE."
                )

            try:
                self._body = self.read()
            except OSError as e:
                raise UnreadablePostError(*e.args) from e
            finally:
                self._stream.close()
            self._stream = BytesIO(self._body)
        return self._body

    def _mark_post_parse_error(self) -> None:
        self._data = QueryDict()
        self._files = MultiValueDict()

    def _load_data_and_files(self) -> None:
        """Populate self._data and self._files"""

        if self._read_started and not hasattr(self, "_body"):
            self._mark_post_parse_error()
            return

        if self.content_type.startswith("application/json"):
            try:
                self._data = json.loads(self.body)
                self._files = MultiValueDict()
            except json.JSONDecodeError:
                self._mark_post_parse_error()
                raise
        elif self.content_type == "multipart/form-data":
            if hasattr(self, "_body"):
                # Use already read data
                data = BytesIO(self._body)
            else:
                data = self
            try:
                self._data, self._files = self.parse_file_upload(self.meta, data)
            except (MultiPartParserError, TooManyFilesSent):
                # An error occurred while parsing POST data. Since when
                # formatting the error the request handler might access
                # self.POST, set self._post and self._file to prevent
                # attempts to parse POST data again.
                self._mark_post_parse_error()
                raise
        elif self.content_type == "application/x-www-form-urlencoded":
            self._data, self._files = (
                QueryDict(self.body, encoding=self._encoding),
                MultiValueDict(),
            )
        else:
            self._data, self._files = (
                QueryDict(encoding=self._encoding),
                MultiValueDict(),
            )

    def close(self) -> None:
        if hasattr(self, "_files"):
            for f in chain.from_iterable(list_[1] for list_ in self._files.lists()):
                f.close()

    # File-like and iterator interface.
    #
    # Expects self._stream to be set to an appropriate source of bytes by
    # a corresponding request subclass (e.g. WSGIRequest).
    # Also when request data has already been read by request.data or
    # request.body, self._stream points to a BytesIO instance
    # containing that data.

    def read(self, *args: Any, **kwargs: Any) -> bytes:
        self._read_started = True
        try:
            return self._stream.read(*args, **kwargs)
        except OSError as e:
            raise UnreadablePostError(*e.args) from e

    def readline(self, *args: Any, **kwargs: Any) -> bytes:
        self._read_started = True
        try:
            return self._stream.readline(*args, **kwargs)
        except OSError as e:
            raise UnreadablePostError(*e.args) from e

    def __iter__(self) -> Iterator[bytes]:
        return iter(self.readline, b"")

    def readlines(self) -> list[bytes]:
        return list(self)

    def get_signed_cookie(
        self,
        key: str,
        default: str | None = None,
        salt: str = "",
        max_age: int | None = None,
    ) -> str | None:
        """
        Retrieve a cookie value signed with the SECRET_KEY.

        Return default if the cookie doesn't exist or signature verification fails.
        """

        try:
            cookie_value = self.cookies[key]
        except KeyError:
            return default

        return unsign_cookie_value(key, cookie_value, salt, max_age, default)


class RequestHeaders(CaseInsensitiveMapping):
    HTTP_PREFIX = "HTTP_"
    # PEP 333 gives two headers which aren't prepended with HTTP_.
    UNPREFIXED_HEADERS = {"CONTENT_TYPE", "CONTENT_LENGTH"}

    def __init__(self, environ: dict[str, Any]):
        headers = {}
        for header, value in environ.items():
            name = self.parse_header_name(header)
            if name:
                headers[name] = value
        super().__init__(headers)

    def __getitem__(self, key: str) -> str:
        """Allow header lookup using underscores in place of hyphens."""
        return super().__getitem__(key.replace("_", "-"))

    @classmethod
    def parse_header_name(cls, header: str) -> str | None:
        if header.startswith(cls.HTTP_PREFIX):
            header = header.removeprefix(cls.HTTP_PREFIX)
        elif header not in cls.UNPREFIXED_HEADERS:
            return None
        return header.replace("_", "-").title()

    @classmethod
    def to_wsgi_name(cls, header: str) -> str:
        header = header.replace("-", "_").upper()
        if header in cls.UNPREFIXED_HEADERS:
            return header
        return f"{cls.HTTP_PREFIX}{header}"

    @classmethod
    def to_wsgi_names(cls, headers: dict[str, Any]) -> dict[str, Any]:
        return {
            cls.to_wsgi_name(header_name): value
            for header_name, value in headers.items()
        }


class QueryDict(MultiValueDict):
    """
    A specialized MultiValueDict which represents a query string.

    A QueryDict can be used to represent GET or POST data. It subclasses
    MultiValueDict since keys in such data can be repeated, for instance
    in the data from a form with a <select multiple> field.

    By default QueryDicts are immutable, though the copy() method
    will always return a mutable copy.

    Both keys and values set on this class are converted from the given encoding
    (DEFAULT_CHARSET by default) to str.
    """

    # These are both reset in __init__, but is specified here at the class
    # level so that unpickling will have valid values
    _mutable = True
    _encoding = None

    def __init__(
        self,
        query_string: str | bytes | None = None,
        mutable: bool = False,
        encoding: str | None = None,
    ):
        super().__init__()
        self.encoding = encoding or settings.DEFAULT_CHARSET
        query_string = query_string or ""
        parse_qsl_kwargs = {
            "keep_blank_values": True,
            "encoding": self.encoding,
            "max_num_fields": settings.DATA_UPLOAD_MAX_NUMBER_FIELDS,
        }
        if isinstance(query_string, bytes):
            # query_string normally contains URL-encoded data, a subset of ASCII.
            query_bytes = query_string
            try:
                query_string = query_bytes.decode(self.encoding)
            except UnicodeDecodeError:
                # ... but some user agents are misbehaving :-(
                query_string = query_bytes.decode("iso-8859-1")
        try:
            for key, value in parse_qsl(query_string, **parse_qsl_kwargs):
                self.appendlist(key, value)
        except ValueError as e:
            # ValueError can also be raised if the strict_parsing argument to
            # parse_qsl() is True. As that is not used by Plain, assume that
            # the exception was raised by exceeding the value of max_num_fields
            # instead of fragile checks of exception message strings.
            raise TooManyFieldsSent(
                "The number of GET/POST parameters exceeded "
                "settings.DATA_UPLOAD_MAX_NUMBER_FIELDS."
            ) from e
        self._mutable = mutable

    @classmethod
    def fromkeys(
        cls,
        iterable: Any,
        value: str = "",
        mutable: bool = False,
        encoding: str | None = None,
    ) -> QueryDict:
        """
        Return a new QueryDict with keys (may be repeated) from an iterable and
        values from value.
        """
        q = cls("", mutable=True, encoding=encoding)
        for key in iterable:
            q.appendlist(key, value)
        if not mutable:
            q._mutable = False
        return q

    @property
    def encoding(self) -> str:
        if self._encoding is None:
            self._encoding = settings.DEFAULT_CHARSET
        return self._encoding

    @encoding.setter
    def encoding(self, value: str) -> None:
        self._encoding = value

    def _assert_mutable(self) -> None:
        if not self._mutable:
            raise AttributeError("This QueryDict instance is immutable")

    def __setitem__(self, key: str, value: Any) -> None:
        self._assert_mutable()
        key = self.bytes_to_text(key, self.encoding)
        value = self.bytes_to_text(value, self.encoding)
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        self._assert_mutable()
        super().__delitem__(key)

    def __copy__(self) -> QueryDict:
        result = self.__class__("", mutable=True, encoding=self.encoding)
        for key, value in self.lists():
            result.setlist(key, value)
        return result

    def __deepcopy__(self, memo: dict[int, Any]) -> QueryDict:
        result = self.__class__("", mutable=True, encoding=self.encoding)
        memo[id(self)] = result
        for key, value in self.lists():
            result.setlist(copy.deepcopy(key, memo), copy.deepcopy(value, memo))
        return result

    def setlist(self, key: str, list_: list[Any]) -> None:
        self._assert_mutable()
        key = self.bytes_to_text(key, self.encoding)
        list_ = [self.bytes_to_text(elt, self.encoding) for elt in list_]
        super().setlist(key, list_)

    def setlistdefault(
        self, key: str, default_list: list[Any] | None = None
    ) -> list[Any]:
        self._assert_mutable()
        return super().setlistdefault(key, default_list)

    def appendlist(self, key: str, value: Any) -> None:
        self._assert_mutable()
        key = self.bytes_to_text(key, self.encoding)
        value = self.bytes_to_text(value, self.encoding)
        super().appendlist(key, value)

    def pop(self, key: str, *args: Any) -> Any:
        self._assert_mutable()
        return super().pop(key, *args)

    def popitem(self) -> tuple[str, Any]:
        self._assert_mutable()
        return super().popitem()

    def clear(self) -> None:
        self._assert_mutable()
        super().clear()

    def setdefault(self, key: str, default: Any = None) -> Any:
        self._assert_mutable()
        key = self.bytes_to_text(key, self.encoding)
        default = self.bytes_to_text(default, self.encoding)
        return super().setdefault(key, default)

    def copy(self) -> QueryDict:
        """Return a mutable copy of this object."""
        return self.__deepcopy__({})

    def urlencode(self, safe: str | None = None) -> str:
        """
        Return an encoded string of all query string arguments.

        `safe` specifies characters which don't require quoting, for example::

            >>> q = QueryDict(mutable=True)
            >>> q['next'] = '/a&b/'
            >>> q.urlencode()
            'next=%2Fa%26b%2F'
            >>> q.urlencode(safe='/')
            'next=/a%26b/'
        """
        output = []
        if safe:
            safe_bytes: bytes = safe.encode(self.encoding)

            def encode(k: bytes, v: bytes) -> str:
                return f"{quote(k, safe_bytes)}={quote(v, safe_bytes)}"

        else:

            def encode(k: bytes, v: bytes) -> str:
                return urlencode({k: v})

        for k, list_ in self.lists():
            output.extend(
                encode(k.encode(self.encoding), str(v).encode(self.encoding))
                for v in list_
            )
        return "&".join(output)

    # It's neither necessary nor appropriate to use
    # plain.utils.encoding.force_str() for parsing URLs and form inputs. Thus,
    # this slightly more restricted function, used by QueryDict.
    @staticmethod
    def bytes_to_text(s: Any, encoding: str) -> str:
        """
        Convert bytes objects to strings, using the given encoding. Illegally
        encoded input characters are replaced with Unicode "unknown" codepoint
        (\ufffd).

        Return any non-bytes objects without change.
        """
        if isinstance(s, bytes):
            return str(s, encoding, "replace")
        else:
            return s


class MediaType:
    def __init__(self, media_type_raw_line: str | MediaType):
        line = str(media_type_raw_line) if media_type_raw_line else ""
        full_type, self.params = parse_header_parameters(line)
        self.main_type, _, self.sub_type = full_type.partition("/")

    def __str__(self) -> str:
        params_str = "".join(f"; {k}={v}" for k, v in self.params.items())
        return "{}{}{}".format(
            self.main_type,
            (f"/{self.sub_type}") if self.sub_type else "",
            params_str,
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__qualname__}: {self}>"

    @property
    def is_all_types(self) -> bool:
        return self.main_type == "*" and self.sub_type == "*"

    @property
    def quality(self) -> float:
        """Return the quality value from the Accept header (default 1.0)."""
        return float(self.params.get("q", 1.0))

    def match(self, other: str | MediaType) -> bool:
        if self.is_all_types:
            return True
        other = MediaType(other)
        if self.main_type == other.main_type and self.sub_type in {"*", other.sub_type}:
            return True
        return False

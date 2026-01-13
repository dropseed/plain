from __future__ import annotations

import copy
import json
import secrets
import uuid
from collections.abc import Iterator
from functools import cached_property
from io import BytesIO
from itertools import chain
from typing import TYPE_CHECKING, Any, TypeVar, overload
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit

if TYPE_CHECKING:
    from plain.urls import ResolverMatch

from plain.exceptions import ImproperlyConfigured
from plain.http.cookie import unsign_cookie_value
from plain.http.multipartparser import (
    MultiPartParser,
)
from plain.runtime import settings
from plain.utils.datastructures import (
    CaseInsensitiveMapping,
    MultiValueDict,
)
from plain.utils.encoding import iri_to_uri
from plain.utils.http import parse_header_parameters

from .exceptions import (
    BadRequestError400,
    RequestDataTooBigError400,
    TooManyFieldsSentError400,
)

_T = TypeVar("_T")


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
    encoding: str | None = None

    non_picklable_attrs = frozenset(["resolver_match", "_stream"])

    method: str | None
    resolver_match: ResolverMatch | None
    content_type: str | None
    content_params: dict[str, str] | None
    query_params: QueryDict
    cookies: dict[str, str]
    environ: dict[str, Any]
    path: str
    path_info: str
    unique_id: str

    def __init__(self):
        # A unique ID we can use to trace this request
        self.unique_id = str(uuid.uuid4())
        self.resolver_match = None

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
        return RequestHeaders(self.environ)

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

    @cached_property
    def host(self) -> str:
        """
        Return the HTTP host using the environment or request headers.

        Host validation is performed by HostValidationMiddleware, so this
        property can safely return the host without any validation.
        """
        # We try three options, in order of decreasing preference.
        if settings.HTTP_X_FORWARDED_HOST and (
            xff_host := self.headers.get("X-Forwarded-Host")
        ):
            host = xff_host
        elif http_host := self.headers.get("Host"):
            host = http_host
        else:
            # Reconstruct the host using the algorithm from PEP 333.
            host = self.environ["SERVER_NAME"]
            server_port = self.port
            if server_port != ("443" if self.is_https() else "80"):
                host = f"{host}:{server_port}"
        return host

    @cached_property
    def port(self) -> str:
        """Return the port number for the request as a string."""
        if settings.HTTP_X_FORWARDED_PORT and (
            xff_port := self.headers.get("X-Forwarded-Port")
        ):
            port = xff_port
        else:
            port = self.environ["SERVER_PORT"]
        return str(port)

    @cached_property
    def client_ip(self) -> str:
        """Return the client's IP address.

        If HTTP_X_FORWARDED_FOR is True, checks the X-Forwarded-For header first
        (using the first/leftmost IP). Otherwise returns REMOTE_ADDR directly.

        Only enable HTTP_X_FORWARDED_FOR when behind a trusted proxy that
        overwrites the X-Forwarded-For header.
        """
        if settings.HTTP_X_FORWARDED_FOR:
            if xff := self.headers.get("X-Forwarded-For"):
                return xff.split(",")[0].strip()
        return self.environ["REMOTE_ADDR"]

    @property
    def query_string(self) -> str:
        """Return the raw query string from the request URL."""
        return self.environ.get("QUERY_STRING", "")

    @property
    def content_length(self) -> int:
        """Return the Content-Length header value, or 0 if not provided."""
        try:
            return int(self.environ.get("CONTENT_LENGTH") or 0)
        except (ValueError, TypeError):
            return 0

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

        return "{}{}{}".format(
            escape_uri_path(self.path),
            "/" if force_append_slash and not self.path.endswith("/") else "",
            ("?" + (iri_to_uri(self.query_string) or "")) if self.query_string else "",
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
            if ":" not in settings.HTTPS_PROXY_HEADER:
                raise ImproperlyConfigured(
                    "The HTTPS_PROXY_HEADER setting must be a string in the format "
                    "'Header-Name: value' (e.g., 'X-Forwarded-Proto: https')."
                )
            header, secure_value = settings.HTTPS_PROXY_HEADER.split(":", 1)
            header = header.strip()
            secure_value = secure_value.strip()
            header_value = self.headers.get(header)
            if header_value is not None:
                header_value, *_ = header_value.split(",", 1)
                return "https" if header_value.strip() == secure_value else "http"
        return self._get_scheme()

    def is_https(self) -> bool:
        return self.scheme == "https"

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
                and self.content_length > settings.DATA_UPLOAD_MAX_MEMORY_SIZE
            ):
                raise RequestDataTooBigError400(
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

    @cached_property
    def _multipart_data(self) -> tuple[QueryDict, MultiValueDict]:
        """Parse multipart/form-data. Used internally by form_data and files properties.

        Raises MultiPartParserError or TooManyFilesSentError400 for malformed uploads,
        which are handled by response_for_exception() as 400 errors.
        """
        return MultiPartParser(self).parse()

    @cached_property
    def json_data(self) -> dict[str, Any]:
        """
        Parsed JSON object from request body.

        Returns dict for JSON objects.
        Raises BadRequestError400 if JSON is invalid or not an object.
        Raises ValueError if request content-type is not JSON.

        Use this when you expect JSON object data and want type-safe dict access.
        """
        if not self.content_type or not self.content_type.startswith(
            "application/json"
        ):
            raise ValueError(
                f"Request content-type is not JSON (got: {self.content_type})"
            )
        try:
            parsed = json.loads(self.body)
        except json.JSONDecodeError as e:
            raise BadRequestError400(f"Invalid JSON in request body: {e}") from e

        if not isinstance(parsed, dict):
            raise BadRequestError400(
                f"Expected JSON object, got {type(parsed).__name__}"
            )
        return parsed

    @cached_property
    def form_data(self) -> QueryDict:
        """
        Form data from POST body.

        Returns QueryDict for application/x-www-form-urlencoded or
        multipart/form-data content types.
        Returns empty QueryDict if Content-Type is missing (e.g., GET requests).
        Raises ValueError if request has a different content-type with a body.

        Use this when you expect form data and want type-safe QueryDict access.
        """
        if self.content_type == "application/x-www-form-urlencoded":
            return QueryDict(self.body, encoding=self.encoding)
        elif self.content_type == "multipart/form-data":
            return self._multipart_data[0]
        elif not self.content_type:
            # No Content-Type (e.g., GET requests) - return empty QueryDict
            return QueryDict(b"", encoding=self.encoding)
        else:
            raise ValueError(
                f"Request content-type is not form data (got: {self.content_type})"
            )

    @cached_property
    def files(self) -> MultiValueDict:
        """
        File uploads from multipart/form-data requests.

        Returns MultiValueDict of uploaded files for multipart requests,
        or empty MultiValueDict for other content types.
        """
        if self.content_type == "multipart/form-data":
            return self._multipart_data[1]
        return MultiValueDict()

    def close(self) -> None:
        # Close any uploaded files if they were accessed
        if self.content_type == "multipart/form-data" and hasattr(
            self, "_multipart_data"
        ):
            _, files = self._multipart_data
            for f in chain.from_iterable(list_[1] for list_ in files.lists()):
                f.close()

    # File-like and iterator interface.
    #
    # Expects self._stream to be set to an appropriate source of bytes by
    # a corresponding request subclass (e.g. WSGIRequest).
    # Also when request data has already been read by request.json_data,
    # request.form_data, or request.body, self._stream points to a BytesIO
    # instance containing that data.

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
        parse_qsl_kwargs: dict[str, Any] = {
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
            raise TooManyFieldsSentError400(
                "The number of GET/POST parameters exceeded "
                "settings.DATA_UPLOAD_MAX_NUMBER_FIELDS."
            ) from e
        self._mutable = mutable

    @classmethod
    def fromkeys(  # type: ignore[override]
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

    def __getitem__(self, key: str) -> str:  # type: ignore[override]
        """
        Return the last data value for this key as a string.
        QueryDict values are always strings.
        """
        return super().__getitem__(key)

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

    def getlist(self, key: str, default: list[str] | None = None) -> list[str]:
        """
        Return the list of values for the key as strings.
        QueryDict values are always strings.
        """
        return super().getlist(key, default)

    @overload
    def get(self, key: str) -> str | None: ...

    @overload
    def get(self, key: str, default: str) -> str: ...

    @overload
    def get(self, key: str, default: _T) -> str | _T: ...

    def get(self, key: str, default: Any = None) -> str | Any:  # type: ignore[override]
        """
        Return the last data value for the passed key. If key doesn't exist
        or value is an empty list, return `default`.

        QueryDict values are always strings (from URL parsing), but the
        return type preserves the type of the default parameter for type safety.

        Examples:
            get("page")         -> str | None
            get("page", "1")    -> str
            get("page", 1)      -> str | int
        """
        return super().get(key, default)

    @overload
    def pop(self, key: str) -> str: ...

    @overload
    def pop(self, key: str, default: str) -> str: ...

    @overload
    def pop(self, key: str, default: _T) -> str | _T: ...

    def pop(self, key: str, *args: Any) -> str | Any:  # type: ignore[override]
        """
        Remove and return a value for the key.

        QueryDict values are always strings, but the return type preserves
        the type of the default parameter for type safety.

        Examples:
            pop("page")         -> str (or raises KeyError)
            pop("page", "1")    -> str
            pop("page", 1)      -> str | int
        """
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

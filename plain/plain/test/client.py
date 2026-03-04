from __future__ import annotations

import json
from http import HTTPStatus
from http.cookies import SimpleCookie
from io import BytesIO, IOBase
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse, urlsplit

from plain.http import QueryDict, Request
from plain.internal.handlers.base import BaseHandler
from plain.json import PlainJSONEncoder
from plain.signals import request_started
from plain.urls import get_resolver
from plain.utils.encoding import force_bytes
from plain.utils.functional import SimpleLazyObject
from plain.utils.http import urlencode
from plain.utils.regex_helper import _lazy_re_compile

from .encoding import encode_multipart
from .exceptions import RedirectCycleError

if TYPE_CHECKING:
    from plain.http import ResponseBase
    from plain.urls import ResolverMatch

__all__ = (
    "Client",
    "ClientResponse",
    "RequestFactory",
)


_BOUNDARY = "BoUnDaRyStRiNg"
_MULTIPART_CONTENT = f"multipart/form-data; boundary={_BOUNDARY}"
_CONTENT_TYPE_RE = _lazy_re_compile(r".*; charset=([\w-]+);?")
# Structured suffix spec: https://tools.ietf.org/html/rfc6838#section-4.2.8
_JSON_CONTENT_TYPE_RE = _lazy_re_compile(r"^application\/(.+\+)?json")


class ClientResponse:
    """
    Response wrapper returned by test Client with test-specific attributes.

    Wraps any ResponseBase subclass and adds attributes useful for testing,
    while delegating all other attribute access to the wrapped response.
    """

    def __init__(
        self,
        response: ResponseBase,
        client: Client,
    ):
        # Store wrapped response in __dict__ directly to avoid __setattr__ recursion
        object.__setattr__(self, "_response", response)
        object.__setattr__(self, "_json_cache", None)
        # Test-specific attributes
        self.client = client
        self.request: Request
        self.redirect_chain: list[tuple[str, int]]
        self.resolver_match: SimpleLazyObject | ResolverMatch
        # Optional: set by plain.auth if available
        # self.user: Model

    def json(self, **extra: Any) -> Any:
        """Parse response content as JSON."""
        _json_cache = object.__getattribute__(self, "_json_cache")
        if _json_cache is None:
            response = object.__getattribute__(self, "_response")
            content_type = response.headers.get("Content-Type", "")
            if not _JSON_CONTENT_TYPE_RE.match(content_type):
                raise ValueError(
                    f'Content-Type header is "{content_type}", not "application/json"'
                )
            _json_cache = json.loads(
                response.content.decode(response.charset),
                **extra,
            )
            object.__setattr__(self, "_json_cache", _json_cache)
        return _json_cache

    @property
    def url(self) -> str:
        """
        Return redirect URL if this is a redirect response.

        This property exists on RedirectResponse and is added for redirects.
        """
        response = object.__getattribute__(self, "_response")
        if hasattr(response, "url"):
            return response.url
        # For non-redirect responses, try to get Location header
        if "Location" in response.headers:
            return response.headers["Location"]
        raise AttributeError(f"{response.__class__.__name__} has no attribute 'url'")

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the wrapped response."""
        return getattr(object.__getattribute__(self, "_response"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Set attributes on the wrapper itself."""
        object.__setattr__(self, name, value)

    def __repr__(self) -> str:
        """Return repr of wrapped response."""
        return repr(object.__getattribute__(self, "_response"))


class FakePayload(IOBase):
    """
    A wrapper around BytesIO that restricts what can be read since data from
    the network can't be sought and cannot be read outside of its content
    length. This makes sure that views can't do anything under the test client
    that wouldn't work in real life.
    """

    def __init__(self, initial_bytes: bytes | None = None) -> None:
        self.__content = BytesIO()
        self.__len = 0
        self.read_started = False
        if initial_bytes is not None:
            self.write(initial_bytes)

    def __len__(self) -> int:
        return self.__len

    def read(self, size: int = -1, /) -> bytes:
        if not self.read_started:
            self.__content.seek(0)
            self.read_started = True
        if size == -1 or size is None:
            size = self.__len
        else:
            size = min(size, self.__len)
        content = self.__content.read(size)
        self.__len -= len(content)
        return content

    def readline(self, size: int | None = -1, /) -> bytes:
        if not self.read_started:
            self.__content.seek(0)
            self.read_started = True
        if size is None or size == -1:
            size = self.__len
        else:
            size = min(size, self.__len)
        content = self.__content.readline(size)
        self.__len -= len(content)
        return content

    def write(self, b: bytes | str, /) -> None:
        if self.read_started:
            raise ValueError("Unable to write a payload after it's been read")
        content = force_bytes(b)
        self.__content.write(content)
        self.__len += len(content)


def _conditional_content_removal(
    request: Request, response: ResponseBase
) -> ResponseBase:
    """
    Simulate the behavior of most web servers by removing the content of
    responses for HEAD requests, 1xx, 204, and 304 responses. Ensure
    compliance with RFC 9112 Section 6.3.
    """
    if 100 <= response.status_code < 200 or response.status_code in (204, 304):
        if response.streaming:  # type: ignore[attr-defined]
            response.streaming_content = []  # type: ignore[attr-defined]
        else:
            response.content = b""  # type: ignore[attr-defined]
    if request.method == "HEAD":
        if response.streaming:  # type: ignore[attr-defined]
            response.streaming_content = []  # type: ignore[attr-defined]
        else:
            response.content = b""  # type: ignore[attr-defined]
    return response


class ClientHandler(BaseHandler):
    """
    An HTTP Handler that can be used for testing purposes. Takes a Request
    object directly and returns the raw Response with the originating
    Request attached to its ``request`` attribute.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def __call__(self, request: Request) -> ResponseBase:
        # Set up middleware if needed. We couldn't do this earlier, because
        # settings weren't available.
        if self._middleware_chain is None:
            self.load_middleware()

        request_started.send(sender=self.__class__, request=request)

        # Request goes through middleware.
        response = self.get_response(request)

        # Simulate behaviors of most web servers.
        _conditional_content_removal(request, response)

        # Attach the originating request to the response so that it could be
        # later retrieved.
        response.request = request  # type: ignore[attr-defined]

        # Emulate a server by calling the close method on completion.
        response.close()

        return response


class RequestFactory:
    """
    Class that lets you create mock Request objects for use in testing.

    Usage:

    rf = RequestFactory()
    get_request = rf.get('/hello/')
    post_request = rf.post('/submit/', {'foo': 'bar'})

    Once you have a request object you can pass it to any view function,
    just as if that view had been hooked up using a urlrouter.
    """

    def __init__(
        self,
        *,
        json_encoder: type[json.JSONEncoder] = PlainJSONEncoder,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.json_encoder = json_encoder
        self._default_headers: dict[str, str] = headers or {}
        self.cookies: SimpleCookie[str] = SimpleCookie()

    def _build_request(
        self,
        method: str,
        path: str,
        *,
        data: bytes = b"",
        content_type: str = "",
        query_string: str = "",
        secure: bool = True,
        server_name: str = "testserver",
        server_port: str = "",
        headers: dict[str, str] | None = None,
    ) -> Request:
        """Build a Request object directly from the given parameters."""
        # Merge headers: defaults first, then per-request overrides
        all_headers: dict[str, str] = dict(self._default_headers)
        if headers:
            all_headers.update(headers)

        # Add cookies
        cookie_str = "; ".join(
            sorted(
                f"{morsel.key}={morsel.coded_value}" for morsel in self.cookies.values()
            )
        )
        if cookie_str:
            all_headers["Cookie"] = cookie_str

        # Add content headers when there's a body
        if data:
            all_headers["Content-Type"] = content_type
            all_headers["Content-Length"] = str(len(data))

        # Normalize header names to Title-Case so that direct dict lookups
        # (e.g. _headers.get("Cookie")) work regardless of caller casing.
        normalized_headers = {
            k.replace("_", "-").title(): v for k, v in all_headers.items()
        }

        request = Request(
            method=method,
            path=path,
            headers=normalized_headers,
            query_string=query_string,
            scheme="https" if secure else "http",
            server_name=server_name,
            server_port=server_port or ("443" if secure else "80"),
            remote_addr="127.0.0.1",
        )

        payload = FakePayload(data) if data else FakePayload(b"")
        request._stream = payload
        request._read_started = False

        return request

    def request(self, **kwargs: Any) -> Request:
        "Construct a generic request object."
        return self._build_request(**kwargs)

    def _encode_data(self, data: dict[str, Any] | str, content_type: str) -> bytes:
        if content_type is _MULTIPART_CONTENT:
            return encode_multipart(_BOUNDARY, data)  # type: ignore[arg-type]
        else:
            # Encode the content so that the byte representation is correct.
            match = _CONTENT_TYPE_RE.match(content_type)
            if match:
                charset = match[1]
            else:
                charset = "utf-8"
            return force_bytes(data, encoding=charset)

    def _encode_json(self, data: Any, content_type: str) -> Any:
        """
        Return encoded JSON if data is a dict, list, or tuple and content_type
        is application/json.
        """
        should_encode = _JSON_CONTENT_TYPE_RE.match(content_type) and isinstance(
            data, dict | list | tuple
        )
        return json.dumps(data, cls=self.json_encoder) if should_encode else data

    def generic(
        self,
        method: str,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
        query_string: str = "",
        server_name: str = "testserver",
        server_port: str = "",
    ) -> Request:
        """Construct an arbitrary HTTP request."""
        parsed = urlparse(str(path))  # path can be lazy
        path = parsed.path
        if parsed.params:
            path += ";" + parsed.params
        data = force_bytes(data, "utf-8")
        if not query_string:
            query_string = parsed.query
        return self._build_request(
            method=method,
            path=path,
            data=data,
            content_type=content_type,
            query_string=query_string,
            secure=secure,
            server_name=server_name,
            server_port=server_port,
            headers=headers,
        )

    def get(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> Request:
        """Construct a GET request."""
        data = {} if data is None else data
        return self.generic(
            "GET",
            path,
            secure=secure,
            headers=headers,
            query_string=urlencode(data, doseq=True),
        )

    def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        content_type: str = _MULTIPART_CONTENT,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> Request:
        """Construct a POST request."""
        data = self._encode_json({} if data is None else data, content_type)
        post_data = self._encode_data(data, content_type)

        return self.generic(
            "POST",
            path,
            post_data,
            content_type,
            secure=secure,
            headers=headers,
        )

    def head(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> Request:
        """Construct a HEAD request."""
        data = {} if data is None else data
        return self.generic(
            "HEAD",
            path,
            secure=secure,
            headers=headers,
            query_string=urlencode(data, doseq=True),
        )

    def trace(
        self,
        path: str,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> Request:
        """Construct a TRACE request."""
        return self.generic("TRACE", path, secure=secure, headers=headers)

    def options(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> Request:
        "Construct an OPTIONS request."
        return self.generic(
            "OPTIONS", path, data, content_type, secure=secure, headers=headers
        )

    def put(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> Request:
        """Construct a PUT request."""
        data = self._encode_json(data, content_type)
        return self.generic(
            "PUT", path, data, content_type, secure=secure, headers=headers
        )

    def patch(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> Request:
        """Construct a PATCH request."""
        data = self._encode_json(data, content_type)
        return self.generic(
            "PATCH", path, data, content_type, secure=secure, headers=headers
        )

    def delete(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> Request:
        """Construct a DELETE request."""
        data = self._encode_json(data, content_type)
        return self.generic(
            "DELETE", path, data, content_type, secure=secure, headers=headers
        )


class Client:
    """
    A class that can act as a client for testing purposes.

    It allows the user to compose GET and POST requests, and
    obtain the response that the server gave to those requests.
    The server Response objects are annotated with the details
    of the contexts and templates that were rendered during the
    process of serving the request.

    Client objects are stateful - they will retain cookie (and
    thus session) details for the lifetime of the Client instance.

    This is not intended as a replacement for Twill/Selenium or
    the like - it is here to allow testing against the
    contexts and templates produced by a view, rather than the
    HTML rendered to the end-user.
    """

    def __init__(
        self,
        raise_request_exception: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._request_factory = RequestFactory(headers=headers)
        self.handler = ClientHandler()
        self.raise_request_exception = raise_request_exception

    @property
    def cookies(self) -> SimpleCookie[str]:
        """Access the cookies from the request factory."""
        return self._request_factory.cookies

    @cookies.setter
    def cookies(self, value: SimpleCookie[str]) -> None:
        """Set the cookies on the request factory."""
        self._request_factory.cookies = value

    def request(self, http_request: Request) -> ClientResponse:
        """
        Send a Request through the handler and return a ClientResponse.
        """
        # Make the request
        response = self.handler(http_request)

        # Wrap the response in ClientResponse for test-specific attributes
        client_response = ClientResponse(
            response=response,
            client=self,
        )

        # Re-raise the exception if configured to do so
        # Only 5xx errors have response.exception set
        if client_response.exception and self.raise_request_exception:
            raise client_response.exception

        # If the request had a user, make it available on the response.
        try:
            from plain.auth.requests import get_request_user

            client_response.user = get_request_user(client_response.request)
        except Exception:
            # ImportError if plain.auth not installed, or other exceptions
            # if session middleware didn't run (e.g. healthcheck)
            pass

        # Attach the ResolverMatch instance to the response.
        # Returns None for paths handled by middleware (e.g. healthcheck)
        # that don't have a corresponding URL route.
        resolver = get_resolver()

        def _resolve_or_none():
            try:
                return resolver.resolve(http_request.path_info)
            except Exception:
                return None

        client_response.resolver_match = SimpleLazyObject(_resolve_or_none)

        # Update persistent cookie data.
        if client_response.cookies:
            self.cookies.update(client_response.cookies)
        return client_response

    def get(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        follow: bool = False,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> ClientResponse:
        """Request a response from the server using GET."""
        request = self._request_factory.get(
            path, data=data, secure=secure, headers=headers
        )
        response = self.request(request)
        if follow:
            response = self._handle_redirects(response, data=data, headers=headers)
        return response

    def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        content_type: str = _MULTIPART_CONTENT,
        follow: bool = False,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> ClientResponse:
        """Request a response from the server using POST."""
        request = self._request_factory.post(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
        )
        response = self.request(request)
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers
            )
        return response

    def head(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        follow: bool = False,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> ClientResponse:
        """Request a response from the server using HEAD."""
        request = self._request_factory.head(
            path, data=data, secure=secure, headers=headers
        )
        response = self.request(request)
        if follow:
            response = self._handle_redirects(response, data=data, headers=headers)
        return response

    def options(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        follow: bool = False,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> ClientResponse:
        """Request a response from the server using OPTIONS."""
        request = self._request_factory.options(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
        )
        response = self.request(request)
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers
            )
        return response

    def put(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        follow: bool = False,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> ClientResponse:
        """Send a resource to the server using PUT."""
        request = self._request_factory.put(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
        )
        response = self.request(request)
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers
            )
        return response

    def patch(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        follow: bool = False,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> ClientResponse:
        """Send a resource to the server using PATCH."""
        request = self._request_factory.patch(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
        )
        response = self.request(request)
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers
            )
        return response

    def delete(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        follow: bool = False,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> ClientResponse:
        """Send a DELETE request to the server."""
        request = self._request_factory.delete(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
        )
        response = self.request(request)
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers
            )
        return response

    def trace(
        self,
        path: str,
        data: Any = "",
        follow: bool = False,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
    ) -> ClientResponse:
        """Send a TRACE request to the server."""
        request = self._request_factory.trace(path, secure=secure, headers=headers)
        response = self.request(request)
        if follow:
            response = self._handle_redirects(response, data=data, headers=headers)
        return response

    def _handle_redirects(
        self,
        response: ClientResponse,
        data: Any = "",
        content_type: str = "",
        headers: dict[str, str] | None = None,
    ) -> ClientResponse:
        """
        Follow any redirects by requesting responses from the server using GET.
        """
        response.redirect_chain = []
        redirect_status_codes = (
            HTTPStatus.MOVED_PERMANENTLY,
            HTTPStatus.FOUND,
            HTTPStatus.SEE_OTHER,
            HTTPStatus.TEMPORARY_REDIRECT,
            HTTPStatus.PERMANENT_REDIRECT,
        )
        while response.status_code in redirect_status_codes:
            response_url = response.url
            redirect_chain = response.redirect_chain
            redirect_chain.append((response_url, response.status_code))

            url = urlsplit(response_url)

            # Inherit server settings from the previous response's request
            secure = response.request.scheme == "https"
            server_name = response.request.server_name
            server_port = response.request.server_port

            if url.scheme:
                secure = url.scheme == "https"
            if url.hostname:
                server_name = url.hostname
            if url.port:
                server_port = str(url.port)

            path = url.path
            # RFC 3986 Section 6.2.3: Empty path should be normalized to "/".
            if not path and url.netloc:
                path = "/"
            # Prepend the request path to handle relative path redirects
            if not path.startswith("/"):
                path = urljoin(response.request.path, path)

            if response.status_code in (
                HTTPStatus.TEMPORARY_REDIRECT,
                HTTPStatus.PERMANENT_REDIRECT,
            ):
                # Preserve request method for 307/308 responses.
                method = response.request.method
                assert method is not None

                if method in ("GET", "HEAD"):
                    # GET/HEAD: re-encode data as query string
                    if isinstance(data, QueryDict):
                        qs = data.urlencode()
                    elif isinstance(data, dict):
                        qs = urlencode(data, doseq=True)
                    else:
                        qs = ""
                    request = self._request_factory._build_request(
                        method=method,
                        path=path,
                        query_string=qs,
                        secure=secure,
                        server_name=server_name,
                        server_port=server_port,
                        headers=headers,
                    )
                else:
                    # POST/PUT/etc: preserve body and add redirect URL's query
                    encoded_data = self._request_factory._encode_json(
                        data, content_type
                    )
                    encoded_data = self._request_factory._encode_data(
                        encoded_data, content_type
                    )
                    request = self._request_factory._build_request(
                        method=method,
                        path=path,
                        data=encoded_data,
                        content_type=content_type,
                        query_string=url.query,
                        secure=secure,
                        server_name=server_name,
                        server_port=server_port,
                        headers=headers,
                    )
            else:
                # Non-307/308: redirect as GET with query from redirect URL
                request = self._request_factory._build_request(
                    method="GET",
                    path=path,
                    query_string=url.query,
                    secure=secure,
                    server_name=server_name,
                    server_port=server_port,
                    headers=headers,
                )
                data = QueryDict(url.query)
                content_type = ""

            response = self.request(request)
            response.redirect_chain = redirect_chain

            if redirect_chain[-1] in redirect_chain[:-1]:
                # Check that we're not redirecting to somewhere we've already
                # been to, to prevent loops.
                raise RedirectCycleError(
                    "Redirect loop detected.", last_response=response
                )
            if len(redirect_chain) > 20:
                # Such a lengthy chain likely also means a loop, but one with
                # a growing path, changing view, or changing query argument;
                # 20 is the value of "network.http.redirection-limit" from Firefox.
                raise RedirectCycleError("Too many redirects.", last_response=response)

        return response

    @property
    def session(self) -> Any:
        """Return the current session variables."""
        from plain.sessions.test import get_client_session

        return get_client_session(self)

    def force_login(self, user: Any) -> None:
        from plain.auth.test import login_client

        login_client(self, user)

    def logout(self) -> None:
        """Log out the user by removing the cookies and session object."""
        from plain.auth.test import logout_client

        logout_client(self)

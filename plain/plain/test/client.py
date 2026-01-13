from __future__ import annotations

import json
from http import HTTPStatus
from http.cookies import SimpleCookie
from io import BytesIO, IOBase
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote_to_bytes, urljoin, urlparse, urlsplit

from plain.http import QueryDict, RequestHeaders
from plain.internal import internalcode
from plain.internal.handlers.base import BaseHandler
from plain.internal.handlers.wsgi import WSGIRequest
from plain.json import PlainJSONEncoder
from plain.runtime import settings
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
        request: dict[str, Any],
    ):
        # Store wrapped response in __dict__ directly to avoid __setattr__ recursion
        object.__setattr__(self, "_response", response)
        object.__setattr__(self, "_json_cache", None)
        # Test-specific attributes
        self.client = client
        self.request = request
        self.wsgi_request: WSGIRequest
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


@internalcode
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
        assert self.__len >= size, (
            "Cannot read more than the available bytes from the HTTP incoming data."
        )
        content = self.__content.read(size)
        self.__len -= len(content)
        return content

    def readline(self, size: int | None = -1, /) -> bytes:
        if not self.read_started:
            self.__content.seek(0)
            self.read_started = True
        if size is None or size == -1:
            size = self.__len
        assert self.__len >= size, (
            "Cannot read more than the available bytes from the HTTP incoming data."
        )
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
    request: WSGIRequest, response: ResponseBase
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


@internalcode
class ClientHandler(BaseHandler):
    """
    An HTTP Handler that can be used for testing purposes. Use the WSGI
    interface to compose requests, but return the raw Response object with
    the originating WSGIRequest attached to its ``wsgi_request`` attribute.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def __call__(self, environ: dict[str, Any]) -> ResponseBase:
        # Set up middleware if needed. We couldn't do this earlier, because
        # settings weren't available.
        if self._middleware_chain is None:
            self.load_middleware()

        request_started.send(sender=self.__class__, environ=environ)
        request = WSGIRequest(environ)

        # Request goes through middleware.
        response = self.get_response(request)

        # Simulate behaviors of most web servers.
        _conditional_content_removal(request, response)

        # Attach the originating request to the response so that it could be
        # later retrieved.
        response.wsgi_request = request  # type: ignore[attr-defined]

        # Emulate a WSGI server by calling the close method on completion.
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
        **defaults: Any,
    ) -> None:
        self.json_encoder = json_encoder
        self.defaults: dict[str, Any] = defaults
        self.cookies: SimpleCookie[str] = SimpleCookie()
        self.errors = BytesIO()
        if headers:
            self.defaults.update(RequestHeaders.to_wsgi_names(headers))

    def _base_environ(self, **request: Any) -> dict[str, Any]:
        """
        The base environment for a request.
        """
        # This is a minimal valid WSGI environ dictionary, plus:
        # - HTTP_COOKIE: for cookie support,
        # - REMOTE_ADDR: often useful, see #8551.
        # See https://www.python.org/dev/peps/pep-3333/#environ-variables
        return {
            "HTTP_COOKIE": "; ".join(
                sorted(
                    f"{morsel.key}={morsel.coded_value}"
                    for morsel in self.cookies.values()
                )
            ),
            "PATH_INFO": "/",
            "REMOTE_ADDR": "127.0.0.1",
            "REQUEST_METHOD": "GET",
            "SCRIPT_NAME": "",
            "SERVER_NAME": "testserver",
            "SERVER_PORT": "80",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": FakePayload(b""),
            "wsgi.errors": self.errors,
            "wsgi.multiprocess": True,
            "wsgi.multithread": False,
            "wsgi.run_once": False,
            **self.defaults,
            **request,
        }

    def request(self, **request: Any) -> WSGIRequest:
        "Construct a generic request object."
        return WSGIRequest(self._base_environ(**request))

    def _encode_data(self, data: dict[str, Any] | str, content_type: str) -> bytes:
        if content_type is _MULTIPART_CONTENT:
            return encode_multipart(_BOUNDARY, data)  # type: ignore[arg-type]
        else:
            # Encode the content so that the byte representation is correct.
            match = _CONTENT_TYPE_RE.match(content_type)
            if match:
                charset = match[1]
            else:
                charset = settings.DEFAULT_CHARSET
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

    def _get_path(self, parsed: Any) -> str:
        path = parsed.path
        # If there are parameters, add them
        if parsed.params:
            path += ";" + parsed.params
        path = unquote_to_bytes(path)
        # Replace the behavior where non-ASCII values in the WSGI environ are
        # arbitrarily decoded with ISO-8859-1.
        # Refs comment in `get_bytes_from_wsgi()`.
        return path.decode("iso-8859-1")

    def get(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> WSGIRequest:
        """Construct a GET request."""
        data = {} if data is None else data
        return self.generic(
            "GET",
            path,
            secure=secure,
            headers=headers,
            **{
                "QUERY_STRING": urlencode(data, doseq=True),
                **extra,
            },
        )

    def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        content_type: str = _MULTIPART_CONTENT,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> WSGIRequest:
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
            **extra,
        )

    def head(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> WSGIRequest:
        """Construct a HEAD request."""
        data = {} if data is None else data
        return self.generic(
            "HEAD",
            path,
            secure=secure,
            headers=headers,
            **{
                "QUERY_STRING": urlencode(data, doseq=True),
                **extra,
            },
        )

    def trace(
        self,
        path: str,
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> WSGIRequest:
        """Construct a TRACE request."""
        return self.generic("TRACE", path, secure=secure, headers=headers, **extra)

    def options(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> WSGIRequest:
        "Construct an OPTIONS request."
        return self.generic(
            "OPTIONS", path, data, content_type, secure=secure, headers=headers, **extra
        )

    def put(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> WSGIRequest:
        """Construct a PUT request."""
        data = self._encode_json(data, content_type)
        return self.generic(
            "PUT", path, data, content_type, secure=secure, headers=headers, **extra
        )

    def patch(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> WSGIRequest:
        """Construct a PATCH request."""
        data = self._encode_json(data, content_type)
        return self.generic(
            "PATCH", path, data, content_type, secure=secure, headers=headers, **extra
        )

    def delete(
        self,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> WSGIRequest:
        """Construct a DELETE request."""
        data = self._encode_json(data, content_type)
        return self.generic(
            "DELETE", path, data, content_type, secure=secure, headers=headers, **extra
        )

    def generic(
        self,
        method: str,
        path: str,
        data: Any = "",
        content_type: str = "application/octet-stream",
        secure: bool = True,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> WSGIRequest:
        """Construct an arbitrary HTTP request."""
        parsed = urlparse(str(path))  # path can be lazy
        data = force_bytes(data, settings.DEFAULT_CHARSET)
        r: dict[str, Any] = {
            "PATH_INFO": self._get_path(parsed),
            "REQUEST_METHOD": method,
            "SERVER_PORT": "443" if secure else "80",
            "wsgi.url_scheme": "https" if secure else "http",
        }
        if data:
            r.update(
                {
                    "CONTENT_LENGTH": str(len(data)),
                    "CONTENT_TYPE": content_type,
                    "wsgi.input": FakePayload(data),
                }
            )
        if headers:
            extra.update(RequestHeaders.to_wsgi_names(headers))
        r.update(extra)
        # If QUERY_STRING is absent or empty, we want to extract it from the URL.
        if not r.get("QUERY_STRING"):
            # WSGI requires latin-1 encoded strings. See get_path_info().
            query_string = parsed[4].encode().decode("iso-8859-1")
            r["QUERY_STRING"] = query_string
        return self.request(**r)


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
        **defaults: Any,
    ) -> None:
        self._request_factory = RequestFactory(headers=headers, **defaults)
        self.handler = ClientHandler()
        self.raise_request_exception = raise_request_exception
        self.extra: dict[str, Any] | None = None
        self.headers: dict[str, str] | None = None

    @property
    def cookies(self) -> SimpleCookie[str]:
        """Access the cookies from the request factory."""
        return self._request_factory.cookies

    @cookies.setter
    def cookies(self, value: SimpleCookie[str]) -> None:
        """Set the cookies on the request factory."""
        self._request_factory.cookies = value

    def request(self, **request: Any) -> ClientResponse:
        """
        Make a generic request. Compose the environment dictionary and pass
        to the handler, return the result of the handler. Assume defaults for
        the query environment, which can be overridden using the arguments to
        the request.
        """
        environ = self._request_factory._base_environ(**request)

        # Make the request
        response = self.handler(environ)

        # Wrap the response in ClientResponse for test-specific attributes
        client_response = ClientResponse(
            response=response,
            client=self,
            request=request,
        )

        # Re-raise the exception if configured to do so
        # Only 5xx errors have response.exception set
        if client_response.exception and self.raise_request_exception:
            raise client_response.exception

        # If the request had a user, make it available on the response.
        try:
            from plain.auth.requests import get_request_user

            client_response.user = get_request_user(client_response.wsgi_request)
        except ImportError:
            pass

        # Attach the ResolverMatch instance to the response.
        resolver = get_resolver()
        client_response.resolver_match = SimpleLazyObject(
            lambda: resolver.resolve(request["PATH_INFO"]),
        )

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
        **extra: Any,
    ) -> ClientResponse:
        """Request a response from the server using GET."""
        self.extra = extra
        self.headers = headers
        # Build the request using the factory
        wsgi_request = self._request_factory.get(
            path, data=data, secure=secure, headers=headers, **extra
        )
        # Execute and get response
        response = self.request(**wsgi_request.environ)
        if follow:
            response = self._handle_redirects(
                response, data=data, headers=headers, **extra
            )
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
        **extra: Any,
    ) -> ClientResponse:
        """Request a response from the server using POST."""
        self.extra = extra
        self.headers = headers
        # Build the request using the factory
        wsgi_request = self._request_factory.post(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
            **extra,
        )
        # Execute and get response
        response = self.request(**wsgi_request.environ)
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers, **extra
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
        **extra: Any,
    ) -> ClientResponse:
        """Request a response from the server using HEAD."""
        self.extra = extra
        self.headers = headers
        # Build the request using the factory
        wsgi_request = self._request_factory.head(
            path, data=data, secure=secure, headers=headers, **extra
        )
        # Execute and get response
        response = self.request(**wsgi_request.environ)
        if follow:
            response = self._handle_redirects(
                response, data=data, headers=headers, **extra
            )
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
        **extra: Any,
    ) -> ClientResponse:
        """Request a response from the server using OPTIONS."""
        self.extra = extra
        self.headers = headers
        # Build the request using the factory
        wsgi_request = self._request_factory.options(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
            **extra,
        )
        # Execute and get response
        response = self.request(**wsgi_request.environ)
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers, **extra
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
        **extra: Any,
    ) -> ClientResponse:
        """Send a resource to the server using PUT."""
        self.extra = extra
        self.headers = headers
        # Build the request using the factory
        wsgi_request = self._request_factory.put(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
            **extra,
        )
        # Execute and get response
        response = self.request(**wsgi_request.environ)
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers, **extra
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
        **extra: Any,
    ) -> ClientResponse:
        """Send a resource to the server using PATCH."""
        self.extra = extra
        self.headers = headers
        # Build the request using the factory
        wsgi_request = self._request_factory.patch(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
            **extra,
        )
        # Execute and get response
        response = self.request(**wsgi_request.environ)
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers, **extra
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
        **extra: Any,
    ) -> ClientResponse:
        """Send a DELETE request to the server."""
        self.extra = extra
        self.headers = headers
        # Build the request using the factory
        wsgi_request = self._request_factory.delete(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
            **extra,
        )
        # Execute and get response
        response = self.request(**wsgi_request.environ)
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers, **extra
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
        **extra: Any,
    ) -> ClientResponse:
        """Send a TRACE request to the server."""
        self.extra = extra
        self.headers = headers
        # Build the request using the factory
        wsgi_request = self._request_factory.trace(
            path, data=data, secure=secure, headers=headers, **extra
        )
        # Execute and get response
        response = self.request(**wsgi_request.environ)
        if follow:
            response = self._handle_redirects(
                response, data=data, headers=headers, **extra
            )
        return response

    def _handle_redirects(
        self,
        response: ClientResponse,
        data: Any = "",
        content_type: str = "",
        headers: dict[str, str] | None = None,
        **extra: Any,
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
            if url.scheme:
                extra["wsgi.url_scheme"] = url.scheme
            if url.hostname:
                extra["SERVER_NAME"] = url.hostname
            if url.port:
                extra["SERVER_PORT"] = str(url.port)

            path = url.path
            # RFC 3986 Section 6.2.3: Empty path should be normalized to "/".
            if not path and url.netloc:
                path = "/"
            # Prepend the request path to handle relative path redirects
            if not path.startswith("/"):
                path = urljoin(response.request["PATH_INFO"], path)

            if response.status_code in (
                HTTPStatus.TEMPORARY_REDIRECT,
                HTTPStatus.PERMANENT_REDIRECT,
            ):
                # Preserve request method and query string (if needed)
                # post-redirect for 307/308 responses.
                request_method_name = response.request["REQUEST_METHOD"].lower()
                if request_method_name not in ("get", "head"):
                    extra["QUERY_STRING"] = url.query
                request_method = getattr(self, request_method_name)
            else:
                request_method = self.get
                data = QueryDict(url.query)
                content_type = ""

            response = request_method(
                path,
                data=data,
                content_type=content_type,
                follow=False,
                headers=headers,
                **extra,
            )
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

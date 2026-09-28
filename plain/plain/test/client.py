import asyncio
import contextvars
import json
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from io import BytesIO, IOBase
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse, urlsplit

from opentelemetry import context as otel_context
from opentelemetry import trace
from plain.http import (
    Request,
    WebSocketResponse,
    content_length_forbidden,
)
from plain.internal.handlers.base import BaseHandler
from plain.internal.handlers.response_lifecycle import ResponseLifecycle
from plain.json import PlainJSONEncoder
from plain.urls import get_resolver
from plain.utils.encoding import force_bytes
from plain.utils.functional import SimpleLazyObject
from plain.utils.http import urlencode
from plain.utils.regex_helper import _lazy_re_compile

from .encoding import encode_multipart
from .exceptions import RedirectCycleError

if TYPE_CHECKING:
    from plain.http import Response
    from plain.urls import ResolverMatch

    from .websocket import WebSocketTestConnection

__all__ = [
    "Client",
    "ClientResponse",
    "RequestFactory",
]


_BOUNDARY = "BoUnDaRyStRiNg"
_MULTIPART_CONTENT = f"multipart/form-data; boundary={_BOUNDARY}"
# Structured suffix spec: https://tools.ietf.org/html/rfc6838#section-4.2.8
_JSON_CONTENT_TYPE_RE = _lazy_re_compile(r"^application\/(.+\+)?json")
_CHARSET_RE = _lazy_re_compile(r".*; charset=([\w-]+);?")

_REDIRECT_STATUS_CODES = (
    HTTPStatus.MOVED_PERMANENTLY,
    HTTPStatus.FOUND,
    HTTPStatus.SEE_OTHER,
    HTTPStatus.TEMPORARY_REDIRECT,
    HTTPStatus.PERMANENT_REDIRECT,
)


class ClientResponse:
    """
    Response wrapper returned by test Client.

    Wraps any Response subclass and adds assertable data useful for testing,
    while delegating all other attribute access to the wrapped response.
    """

    def __init__(
        self,
        *,
        response: Response,
        content: bytes,
        client: Client,
        status_code: int,
    ):
        # Store wrapper-private state directly — __setattr__ delegates
        # anything not in _test_attributes to the wrapped response.
        object.__setattr__(self, "_response", response)
        object.__setattr__(self, "_content", content)
        object.__setattr__(self, "_status_code", status_code)
        object.__setattr__(self, "_json_cache", None)
        # Test-specific attributes
        self.client = client
        self.request: Request
        self.redirect_chain: list[tuple[str, int]]
        self.resolver_match: SimpleLazyObject | ResolverMatch

    @property
    def status_code(self) -> int:
        """The status that went out — the view's, unless its streaming body
        failed before producing anything, which a server answers with 500."""
        return self._status_code

    @property
    def body(self) -> bytes:
        """The body the response sent — for a streaming response too, read to
        the end the way a server sends it (empty for HEAD, 204, 304)."""
        return self._content

    @property
    def content(self) -> bytes:
        """The same bytes as `body`, under the name the response itself uses."""
        return self._content

    @property
    def text(self) -> str:
        """The body the response sent, decoded as a string."""
        return self._content.decode(self._response.charset)

    @property
    def json_data(self) -> Any:
        """The body the response sent, parsed as JSON (requires a JSON content type)."""
        if self._json_cache is None:
            content_type = self._response.headers.get("Content-Type", "")
            if not _JSON_CONTENT_TYPE_RE.match(content_type):
                raise ValueError(
                    f'Content-Type header is "{content_type}", not "application/json"'
                )
            object.__setattr__(
                self,
                "_json_cache",
                json.loads(self._content.decode(self._response.charset)),
            )
        return self._json_cache

    @property
    def redirect_to(self) -> str | None:
        """The redirect target if this is a 3xx response, otherwise None."""
        if 300 <= self.status_code < 400:
            return self._response.headers.get("Location")
        return None

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the wrapped response."""
        if name == "streaming_content":
            # The client already read it — the wrapped response's iterator
            # is spent, so delegating would quietly return nothing.
            raise AttributeError(
                "The test client reads a streaming body the way a server"
                " sends it — use `response.body`."
            )
        return getattr(object.__getattribute__(self, "_response"), name)

    # Attributes the wrapper owns; everything else belongs to the
    # wrapped response. An explicit list keeps the split intentional —
    # a name-collision rule would shift per response subclass.
    _test_attributes = frozenset(
        {"client", "request", "redirect_chain", "resolver_match"}
    )

    def __setattr__(self, name: str, value: Any) -> None:
        """Delegate response attributes to the wrapped response.

        Assignments to response attributes behave exactly as they would
        on the raw response — `response.status_code = ...` raises the
        same AttributeError. Test-only attributes land on the wrapper.
        """
        if name in type(self)._test_attributes:
            object.__setattr__(self, name, value)
        else:
            response = object.__getattribute__(self, "_response")
            setattr(response, name, value)

    def __repr__(self) -> str:
        """Return repr of wrapped response."""
        return repr(self._response)


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

    def read(self, size: int | None = -1, /) -> bytes:
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


def _strip_forbidden_content_length(response: Response) -> None:
    """A status that can't carry Content-Length (1xx, 204) loses it, as the
    server writers strip it too. HEAD and 304 keep theirs — it describes the
    body a GET would have had."""
    if content_length_forbidden(response.status_code):
        del response.headers["Content-Length"]


class ClientHandler(BaseHandler):
    """
    An HTTP Handler that can be used for testing purposes. Takes a Request
    object directly and returns the raw Response, with the originating
    Request attached to its ``request`` attribute, and the body it sent.
    """

    def __call__(self, request: Request) -> tuple[ResponseLifecycle, bytes]:
        lifecycle = self.run_pipeline(request)

        # Read the body and close, the way a server sends a response — the
        # same ResponseLifecycle the server drives, read on this thread.
        # Bodiless responses (HEAD, 204/304) never read their body.
        content = lifecycle.read()

        response = lifecycle.response
        _strip_forbidden_content_length(response)

        # Attach the originating request to the response so that it could be
        # later retrieved.
        setattr(response, "request", request)
        return lifecycle, content

    def run_pipeline(self, request: Request) -> ResponseLifecycle:
        """Run the request through middleware and the view.

        Returns what `handle()` returns to the server: the response as a
        `ResponseLifecycle`, not yet read or closed. `__call__` reads it;
        `Client.websocket()` runs the socket from it.
        """
        # Set up middleware if needed. We couldn't do this earlier, because
        # settings weren't available.
        if self._middleware_chain is None:
            self.load_middleware()

        from plain.internal.handlers.base import _AsyncViewPending

        span = self._start_request_span(request)
        started = time.perf_counter()
        token = otel_context.attach(trace.set_span_in_context(span))
        try:
            # Call the sync pipeline directly — no event loop needed for sync
            # views. This keeps the test client usable from both sync tests and
            # async tests (where asyncio.run() would raise).
            result = self._run_sync_pipeline(request)

            if isinstance(result, _AsyncViewPending):
                response = self._handle_async_view(request, result)
            else:
                response = result

            # The context the body is read in — copied from the ambient
            # context the pipeline ran in (so the body sees the test's
            # database transaction), with the request span current so the
            # body's queries land in the request's trace.
            request_context = contextvars.copy_context()
        except BaseException as exc:
            self._fail_request_span(span, exc)
            raise
        finally:
            otel_context.detach(token)

        return self._response_lifecycle(
            response,
            request=request,
            request_context=request_context,
            span=span,
            started=started,
            executor=None,
        )

    def _handle_async_view(self, request: Request, pending: Any) -> Response:
        """Await an async view coroutine and run after-middleware."""
        from plain.internal.handlers.exception import response_for_exception

        async def _run() -> Response:
            try:
                resp = await pending.coroutine
                self._check_response(resp, pending.view_class)
            except Exception as exc:
                resp = response_for_exception(request, exc)

            return resp

        response = asyncio.run(_run())

        # Run after-middleware on the calling thread (same as before-middleware)
        return self._finish_pipeline(request, response, pending.ran_before)


def _encode_request_body(
    *,
    form_data: dict[str, Any] | None,
    json_data: Any,
    body: bytes | str | None,
    files: dict[str, Any] | None,
    content_type: str | None,
    json_encoder: type[json.JSONEncoder],
) -> tuple[bytes, str]:
    """
    Encode the body arguments into (bytes, content_type).

    Exactly one body source may be given: form_data (optionally with files),
    json_data, or a raw body. `content_type` only applies to a raw body.

    A form encodes the way a browser would: urlencoded, and multipart only
    when there are files. Views under test then see the content type they'd
    see in production.
    """
    sources = [
        form_data is not None or files is not None,
        json_data is not None,
        body is not None,
    ]
    if sum(sources) > 1:
        raise TypeError(
            "Pass only one of form_data/files, json_data, or body per request"
        )
    if content_type is not None and body is None:
        if not any(sources):
            # `post(path, content_type="application/json")` with nothing to
            # send. Building an empty body here would hand the view a b"" that
            # its content type says is parseable, and the failure would
            # surface somewhere further in. Say it at the call instead.
            raise TypeError(
                "content_type needs a body — pass body=... alongside it "
                '(body=b"" for a deliberately empty one)'
            )
        raise TypeError(
            "content_type only applies to a raw body — form_data and json_data set their own"
        )

    if json_data is not None:
        return (
            json.dumps(json_data, cls=json_encoder).encode(),
            "application/json",
        )

    if body is not None:
        resolved_content_type = content_type or "application/octet-stream"
        if isinstance(body, str):
            # Encode a string body with the charset the content type
            # declares, so the payload bytes match what the request
            # advertises. Bytes pass through untouched.
            charset_match = _CHARSET_RE.match(resolved_content_type)
            charset = charset_match[1] if charset_match else "utf-8"
            body = body.encode(charset)
        return (body, resolved_content_type)

    if files:
        # Files can only travel as multipart, and any form fields sent with
        # them ride along in the same body.
        merged: dict[str, Any] = dict(form_data or {})
        merged.update(files)
        return (
            encode_multipart(_BOUNDARY, merged),
            _MULTIPART_CONTENT,
        )

    if form_data is not None or files is not None:
        # A plain form — what a browser (and htmx) sends without a file input.
        return (
            urlencode(form_data or {}, doseq=True).encode(),
            "application/x-www-form-urlencoded",
        )

    return (b"", "")


class RequestFactory:
    """
    Class that lets you create mock Request objects for use in testing.

    Usage:

        rf = RequestFactory()
        get_request = rf.get("/hello/")
        post_request = rf.post("/submit/", form_data={"foo": "bar"})

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
        self.cookies: SimpleCookie = SimpleCookie()

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
        # A URL can carry its own query string; merge it in front of any
        # explicitly-passed query string.
        parsed = urlparse(str(path))  # path can be lazy
        path = parsed.path
        if parsed.params:
            path += ";" + parsed.params
        if parsed.query:
            query_string = (
                f"{parsed.query}&{query_string}" if query_string else parsed.query
            )

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

        # Content headers follow the content type, not the byte count: a POST
        # of an empty form still declares what it is, with Content-Length: 0,
        # the same as a browser submitting a form with nothing filled in.
        # Requests with no body source at all (a GET) resolve to no content
        # type and get neither header.
        if content_type:
            all_headers["Content-Type"] = content_type
            all_headers["Content-Length"] = str(len(data))

        request = Request(
            method=method,
            path=path,
            headers=all_headers,
            query_string=query_string,
            server_scheme="https" if secure else "http",
            server_name=server_name,
            server_port=server_port or ("443" if secure else "80"),
            remote_addr="127.0.0.1",
        )

        payload = FakePayload(data) if data else FakePayload(b"")
        request._stream = payload
        request._read_started = False

        return request

    def request(
        self,
        *,
        method: str,
        path: str,
        data: bytes = b"",
        content_type: str = "",
        query_string: str = "",
        secure: bool = True,
        server_name: str = "testserver",
        server_port: str = "",
        headers: dict[str, str] | None = None,
    ) -> Request:
        "Construct a request with an arbitrary method."
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
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        secure: bool = True,
    ) -> Request:
        """Construct a GET request."""
        return self._build_request(
            method="GET",
            path=path,
            query_string=urlencode(query_params or {}, doseq=True),
            secure=secure,
            headers=headers,
        )

    def head(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        secure: bool = True,
    ) -> Request:
        """Construct a HEAD request."""
        return self._build_request(
            method="HEAD",
            path=path,
            query_string=urlencode(query_params or {}, doseq=True),
            secure=secure,
            headers=headers,
        )

    def trace(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        secure: bool = True,
    ) -> Request:
        """Construct a TRACE request."""
        return self._build_request(
            method="TRACE", path=path, secure=secure, headers=headers
        )

    def options(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        secure: bool = True,
    ) -> Request:
        "Construct an OPTIONS request."
        return self._build_request(
            method="OPTIONS",
            path=path,
            query_string=urlencode(query_params or {}, doseq=True),
            secure=secure,
            headers=headers,
        )

    def post(
        self,
        path: str,
        *,
        form_data: dict[str, Any] | None = None,
        json_data: Any = None,
        body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        content_type: str | None = None,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        secure: bool = True,
    ) -> Request:
        """Construct a POST request."""
        return self._body_request(
            "POST",
            path,
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
            query_params=query_params,
            headers=headers,
            secure=secure,
        )

    def put(
        self,
        path: str,
        *,
        form_data: dict[str, Any] | None = None,
        json_data: Any = None,
        body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        content_type: str | None = None,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        secure: bool = True,
    ) -> Request:
        """Construct a PUT request."""
        return self._body_request(
            "PUT",
            path,
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
            query_params=query_params,
            headers=headers,
            secure=secure,
        )

    def patch(
        self,
        path: str,
        *,
        form_data: dict[str, Any] | None = None,
        json_data: Any = None,
        body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        content_type: str | None = None,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        secure: bool = True,
    ) -> Request:
        """Construct a PATCH request."""
        return self._body_request(
            "PATCH",
            path,
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
            query_params=query_params,
            headers=headers,
            secure=secure,
        )

    def delete(
        self,
        path: str,
        *,
        form_data: dict[str, Any] | None = None,
        json_data: Any = None,
        body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        content_type: str | None = None,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        secure: bool = True,
    ) -> Request:
        """Construct a DELETE request."""
        return self._body_request(
            "DELETE",
            path,
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
            query_params=query_params,
            headers=headers,
            secure=secure,
        )

    def _body_request(
        self,
        method: str,
        path: str,
        *,
        form_data: dict[str, Any] | None,
        json_data: Any,
        body: bytes | str | None,
        files: dict[str, Any] | None,
        content_type: str | None,
        query_params: dict[str, Any] | None,
        headers: dict[str, str] | None,
        secure: bool,
    ) -> Request:
        encoded, encoded_content_type = _encode_request_body(
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
            json_encoder=self.json_encoder,
        )
        return self._build_request(
            method=method,
            path=path,
            data=encoded,
            content_type=encoded_content_type,
            query_string=urlencode(query_params or {}, doseq=True),
            secure=secure,
            headers=headers,
        )


class Client:
    """
    A client for making requests against the app without running a server.

    It speaks the same vocabulary as the rest of Plain: `form_data=` arrives
    as `request.form_data`, `json_data=` as `request.json_data`, `files=` as
    `request.files`, and `query_params=` as `request.query_params`.

    Client objects are stateful — they retain cookie (and thus session)
    details for the lifetime of the Client instance.
    """

    def __init__(
        self,
        *,
        raise_request_exception: bool = True,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._request_factory = RequestFactory(headers=headers)
        self.handler = ClientHandler()
        self.raise_request_exception = raise_request_exception

    @property
    def cookies(self) -> SimpleCookie:
        """Access the cookies from the request factory."""
        return self._request_factory.cookies

    @cookies.setter
    def cookies(self, value: SimpleCookie) -> None:
        """Set the cookies on the request factory."""
        self._request_factory.cookies = value

    def request(self, http_request: Request) -> ClientResponse:
        """
        Send a Request through the handler and return a ClientResponse.
        """
        # Make the request
        lifecycle, content = self.handler(http_request)
        # read() always settles a status (None is for a server whose client
        # left before anything went out).
        status_code = lifecycle.sent_status_code
        assert status_code is not None

        # Wrap the response in ClientResponse for test-specific attributes
        client_response = ClientResponse(
            response=lifecycle.response,
            content=content,
            client=self,
            status_code=status_code,
        )

        # Re-raise the exception if configured to do so
        # Only 5xx errors have response.exception set
        if client_response.exception and self.raise_request_exception:
            raise client_response.exception

        # Attach the ResolverMatch instance to the response.
        # Returns None for paths handled by middleware (e.g. healthcheck)
        # that don't have a corresponding URL route.
        resolver = get_resolver()

        def _resolve_or_none():
            try:
                return resolver.resolve(http_request.path)
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
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Request a response from the server using GET."""
        request = self._request_factory.get(
            path, query_params=query_params, headers=headers, secure=secure
        )
        response = self.request(request)
        if follow_redirects:
            response = self._handle_redirects(response, headers=headers)
        return response

    def websocket(
        self,
        path: str,
        *,
        subprotocols: tuple[str, ...] = (),
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        secure: bool = True,
        timeout: float = 5.0,
    ) -> WebSocketTestConnection:
        """Open a websocket to `path` and drive the view's `websocket()` in-process.

            with client.websocket("/live/", subprotocols=("binary",)) as ws:
                ws.send(b"...")
                assert ws.receive() == b"..."

        The handshake runs through the normal pipeline with this client's
        cookies, so auth applies. A response other than the 101 raises
        `WebSocketRejected` carrying it. Every call on the connection has
        a timeout (default 5 s) and raises `TimeoutError` when it elapses.
        """
        from .websocket import (
            WebSocketRejected,
            WebSocketTestConnection,
            handshake_headers,
        )

        handshake = handshake_headers(subprotocols=subprotocols)
        if headers:
            handshake.update(headers)

        request = self._request_factory.get(
            path, query_params=query_params, headers=handshake, secure=secure
        )
        lifecycle = self.handler.run_pipeline(request)
        response = lifecycle.response
        # The handshake request, retrievable the same way as on any response.
        setattr(response, "request", request)
        if response.cookies:
            self.cookies.update(response.cookies)
        if not isinstance(response, WebSocketResponse):
            lifecycle.read()
            raise WebSocketRejected(response)
        return WebSocketTestConnection(lifecycle, timeout=timeout)

    def head(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Request a response from the server using HEAD."""
        request = self._request_factory.head(
            path, query_params=query_params, headers=headers, secure=secure
        )
        response = self.request(request)
        if follow_redirects:
            response = self._handle_redirects(response, headers=headers)
        return response

    def options(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Request a response from the server using OPTIONS."""
        request = self._request_factory.options(
            path, query_params=query_params, headers=headers, secure=secure
        )
        response = self.request(request)
        if follow_redirects:
            response = self._handle_redirects(response, headers=headers)
        return response

    def trace(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Send a TRACE request to the server."""
        request = self._request_factory.trace(path, headers=headers, secure=secure)
        response = self.request(request)
        if follow_redirects:
            response = self._handle_redirects(response, headers=headers)
        return response

    def post(
        self,
        path: str,
        *,
        form_data: dict[str, Any] | None = None,
        json_data: Any = None,
        body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        content_type: str | None = None,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Request a response from the server using POST."""
        return self._body_method(
            "POST",
            path,
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
            query_params=query_params,
            headers=headers,
            follow_redirects=follow_redirects,
            secure=secure,
        )

    def put(
        self,
        path: str,
        *,
        form_data: dict[str, Any] | None = None,
        json_data: Any = None,
        body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        content_type: str | None = None,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Send a resource to the server using PUT."""
        return self._body_method(
            "PUT",
            path,
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
            query_params=query_params,
            headers=headers,
            follow_redirects=follow_redirects,
            secure=secure,
        )

    def patch(
        self,
        path: str,
        *,
        form_data: dict[str, Any] | None = None,
        json_data: Any = None,
        body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        content_type: str | None = None,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Send a resource to the server using PATCH."""
        return self._body_method(
            "PATCH",
            path,
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
            query_params=query_params,
            headers=headers,
            follow_redirects=follow_redirects,
            secure=secure,
        )

    def delete(
        self,
        path: str,
        *,
        form_data: dict[str, Any] | None = None,
        json_data: Any = None,
        body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        content_type: str | None = None,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Send a DELETE request to the server."""
        return self._body_method(
            "DELETE",
            path,
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
            query_params=query_params,
            headers=headers,
            follow_redirects=follow_redirects,
            secure=secure,
        )

    def _body_method(
        self,
        method: str,
        path: str,
        *,
        form_data: dict[str, Any] | None,
        json_data: Any,
        body: bytes | str | None,
        files: dict[str, Any] | None,
        content_type: str | None,
        query_params: dict[str, Any] | None,
        headers: dict[str, str] | None,
        follow_redirects: bool,
        secure: bool,
    ) -> ClientResponse:
        encoded, encoded_content_type = _encode_request_body(
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
            json_encoder=self._request_factory.json_encoder,
        )
        request = self._request_factory._build_request(
            method=method,
            path=path,
            data=encoded,
            content_type=encoded_content_type,
            query_string=urlencode(query_params or {}, doseq=True),
            secure=secure,
            headers=headers,
        )
        response = self.request(request)
        if follow_redirects:
            response = self._handle_redirects(
                response,
                body=encoded,
                content_type=encoded_content_type,
                headers=headers,
            )
        return response

    def _handle_redirects(
        self,
        response: ClientResponse,
        *,
        body: bytes = b"",
        content_type: str = "",
        headers: dict[str, str] | None = None,
    ) -> ClientResponse:
        """
        Follow redirect responses until a non-redirect response is reached.
        """
        response.redirect_chain = []
        while response.status_code in _REDIRECT_STATUS_CODES:
            response_url = response.redirect_to
            if response_url is None:
                break  # a 3xx without a Location header — nowhere to go
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

            method = response.request.method
            if response.status_code in (
                HTTPStatus.TEMPORARY_REDIRECT,
                HTTPStatus.PERMANENT_REDIRECT,
            ) and method not in ("GET", "HEAD"):
                # 307/308 preserve the request method and body.
                request = self._request_factory._build_request(
                    method=method,
                    path=path,
                    data=body,
                    content_type=content_type,
                    query_string=url.query,
                    secure=secure,
                    server_name=server_name,
                    server_port=server_port,
                    headers=headers,
                )
            else:
                # Everything else redirects as a GET without a body.
                request = self._request_factory._build_request(
                    method="GET" if method not in ("GET", "HEAD") else method,
                    path=path,
                    query_string=url.query,
                    secure=secure,
                    server_name=server_name,
                    server_port=server_port,
                    headers=headers,
                )
                body = b""
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

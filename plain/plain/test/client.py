import asyncio
import contextvars
import json
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
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
from plain.utils.http import urlencode
from plain.utils.regex_helper import _lazy_re_compile

from .encoding import encode_multipart
from .exceptions import RedirectCycleError, require_app

if TYPE_CHECKING:
    from plain.http import Response
    from plain.http.response import ResponseHeaders
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


_UNSET: Any = object()


class ClientResponse:
    """
    What the test client got back for one request.

    It has a fixed set of names, listed in `_NAMES`, and reports what was
    *sent*: the status that went out and the bytes that went out. The
    `Response` object the app returned is `returned_response`, for the few
    assertions that are about that object itself.
    """

    _NAMES = (
        "status_code",
        "headers",
        "cookies",
        "body",
        "text",
        "json_data",
        "redirect_to",
        "redirect_chain",
        "request",
        "exception",
        "streaming",
        "resolver_match",
        "returned_response",
    )

    def __init__(
        self,
        *,
        returned_response: Response,
        request: Request,
        status_code: int,
        body: bytes,
    ):
        self._returned_response = returned_response
        self._request = request
        self._status_code = status_code
        self._body = body
        self._redirect_chain: list[tuple[str, int]] = []
        self._json_data: Any = _UNSET
        self._resolver_match: ResolverMatch | None = _UNSET

    @property
    def status_code(self) -> int:
        """The status that went out — the view's, unless its streaming body
        failed before producing anything, which a server answers with 500."""
        return self._status_code

    @property
    def headers(self) -> ResponseHeaders:
        """The response headers."""
        return self._returned_response.headers

    @property
    def cookies(self) -> SimpleCookie:
        """The cookies this response set."""
        return self._returned_response.cookies

    @property
    def body(self) -> bytes:
        """The body the response sent — for a streaming response too, read to
        the end the way a server sends it (empty for HEAD, 204, 304)."""
        return self._body

    @property
    def text(self) -> str:
        """The body the response sent, decoded as a string."""
        return self._body.decode(self._returned_response.charset)

    @property
    def json_data(self) -> Any:
        """The body the response sent, parsed as JSON (requires a JSON content type)."""
        if self._json_data is _UNSET:
            content_type = self.headers.get("Content-Type", "")
            if not _JSON_CONTENT_TYPE_RE.match(content_type):
                raise ValueError(
                    f'Content-Type header is "{content_type}", not "application/json"'
                )
            self._json_data = json.loads(self.text)
        return self._json_data

    @property
    def redirect_to(self) -> str | None:
        """The redirect target if this is a 3xx response, otherwise None."""
        if 300 <= self.status_code < 400:
            return self.headers.get("Location")
        return None

    @property
    def redirect_chain(self) -> list[tuple[str, int]]:
        """The `(url, status_code)` of each redirect `follow_redirects=True`
        followed to get here. Empty when nothing was followed."""
        return self._redirect_chain

    @property
    def request(self) -> Request:
        """The request that produced this response."""
        return self._request

    @property
    def exception(self) -> Exception | None:
        """The exception behind a 5xx response, when
        `Client(raise_request_exception=False)` kept it from being raised."""
        return self._returned_response.exception

    @property
    def streaming(self) -> bool:
        """Whether the body was streamed rather than sent in one piece."""
        return self._returned_response.streaming

    @property
    def resolver_match(self) -> ResolverMatch | None:
        """The URL route the request's path resolves to. None for a path that
        a middleware answered without a route (a healthcheck, a 404)."""
        if self._resolver_match is _UNSET:
            try:
                self._resolver_match = get_resolver().resolve(self._request.path)
            except Exception:
                self._resolver_match = None
        return self._resolver_match

    @property
    def returned_response(self) -> Response:
        """The `Response` object the app returned.

        Everything else here describes what was sent. This is the object
        itself, for asserting on its type or on an attribute only that type
        has. Its own `content` and `status_code` can differ from what went
        out (a HEAD, a 204, a streaming body that failed).
        """
        return self._returned_response

    def __getattr__(self, name: str) -> Any:
        # Only reached for a name that isn't defined above.
        raise AttributeError(
            f"The test client's response has no `{name}`. It has: "
            + ", ".join(type(self)._NAMES)
            + ". The `Response` the app returned is `response.returned_response`."
        )

    def __repr__(self) -> str:
        return (
            f"<ClientResponse status_code={self._status_code}"
            f" of {self._returned_response!r}>"
        )


def _strip_forbidden_content_length(response: Response) -> None:
    """A status that can't carry Content-Length (1xx, 204) loses it, as the
    server writers strip it too. HEAD and 304 keep theirs — it describes the
    body a GET would have had."""
    if content_length_forbidden(response.status_code):
        del response.headers["Content-Length"]


class ClientHandler(BaseHandler):
    """
    An HTTP Handler that can be used for testing purposes. Takes a Request
    object directly and returns the response's lifecycle and the body it sent.
    """

    def __call__(self, request: Request) -> tuple[ResponseLifecycle, bytes]:
        lifecycle = self.run_pipeline(request)

        # Read the body and close, the way a server sends a response — the
        # same ResponseLifecycle the server drives, read on this thread.
        # Bodiless responses (HEAD, 204/304) never read their body.
        body = lifecycle.read()

        _strip_forbidden_content_length(lifecycle.response)
        return lifecycle, body

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
            json.dumps(json_data, cls=PlainJSONEncoder).encode(),
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
    Builds `Request` objects without sending them, for calling a view or a
    middleware directly.

        request = RequestFactory().post("/submit/", form_data={"foo": "bar"})

    It takes the same keywords as `Client`.
    """

    def __init__(self, *, headers: dict[str, str] | None = None) -> None:
        self._default_headers: dict[str, str] = headers or {}
        self.cookies: SimpleCookie = SimpleCookie()

    def request(
        self,
        *,
        method: str,
        path: str,
        query_params: dict[str, Any] | None = None,
        form_data: dict[str, Any] | None = None,
        json_data: Any = None,
        body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        secure: bool = True,
    ) -> Request:
        """Construct a request with any method."""
        encoded_body, encoded_content_type = _encode_request_body(
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
        )
        return self._build_request(
            method=method,
            path=path,
            body=encoded_body,
            content_type=encoded_content_type,
            query_string=urlencode(query_params or {}, doseq=True),
            secure=secure,
            headers=headers,
        )

    def _build_request(
        self,
        *,
        method: str,
        path: str,
        body: bytes = b"",
        content_type: str = "",
        query_string: str = "",
        secure: bool = True,
        server_name: str = "testserver",
        server_port: str = "",
        headers: dict[str, str] | None = None,
    ) -> Request:
        """Build a Request from an already-encoded body and query string.

        `server_name` and `server_port` are here for following a redirect to
        another host. A test sets the host with `headers={"Host": ...}`.
        """
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
            all_headers["Content-Length"] = str(len(body))

        request = Request(
            method=method,
            path=path,
            headers=all_headers,
            query_string=query_string,
            body=body,
            server_scheme="https" if secure else "http",
            server_name=server_name,
            server_port=server_port or ("443" if secure else "80"),
            remote_addr="127.0.0.1",
        )

        return request

    def get(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        secure: bool = True,
    ) -> Request:
        """Construct a GET request."""
        return self.request(
            method="GET",
            path=path,
            query_params=query_params,
            headers=headers,
            secure=secure,
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
        return self.request(
            method="HEAD",
            path=path,
            query_params=query_params,
            headers=headers,
            secure=secure,
        )

    def options(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        secure: bool = True,
    ) -> Request:
        """Construct an OPTIONS request."""
        return self.request(
            method="OPTIONS",
            path=path,
            query_params=query_params,
            headers=headers,
            secure=secure,
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
        return self.request(
            method="POST",
            path=path,
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
        return self.request(
            method="PUT",
            path=path,
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
        return self.request(
            method="PATCH",
            path=path,
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
        return self.request(
            method="DELETE",
            path=path,
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
            query_params=query_params,
            headers=headers,
            secure=secure,
        )


class Client:
    """
    A client for making requests against the app without running a server.

    It speaks the same vocabulary as the rest of Plain: `form_data=` arrives
    as `request.form_data`, `json_data=` as `request.json_data`, `files=` as
    `request.files`, and `query_params=` as `request.query_params`.

    Client objects are stateful — they keep the cookies (and so the session)
    that responses set, for the lifetime of the Client instance. `cookies` is
    that jar: logging a client in is writing the session cookie to it, which
    is what `plain.auth.test.login_client` does.
    """

    def __init__(
        self,
        *,
        raise_request_exception: bool = True,
        headers: dict[str, str] | None = None,
    ) -> None:
        require_app("Client")
        self._request_factory = RequestFactory(headers=headers)
        self._handler = ClientHandler()
        self.raise_request_exception = raise_request_exception

    @property
    def cookies(self) -> SimpleCookie:
        """The cookies sent with every request, updated by every response."""
        return self._request_factory.cookies

    def request(
        self,
        *,
        method: str,
        path: str,
        query_params: dict[str, Any] | None = None,
        form_data: dict[str, Any] | None = None,
        json_data: Any = None,
        body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Make a request with any method."""
        encoded_body, encoded_content_type = _encode_request_body(
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
        )
        request = self._request_factory._build_request(
            method=method,
            path=path,
            body=encoded_body,
            content_type=encoded_content_type,
            query_string=urlencode(query_params or {}, doseq=True),
            secure=secure,
            headers=headers,
        )
        response = self._send(request)
        if follow_redirects:
            response = self._follow_redirects(
                response,
                body=encoded_body,
                content_type=encoded_content_type,
                headers=headers,
            )
        return response

    def _send(self, request: Request) -> ClientResponse:
        """Run a Request through the app and wrap what came back."""
        lifecycle, body = self._handler(request)
        # read() always settles a status (None is for a server whose client
        # left before anything went out).
        status_code = lifecycle.sent_status_code
        assert status_code is not None

        response = ClientResponse(
            returned_response=lifecycle.response,
            request=request,
            status_code=status_code,
            body=body,
        )

        # Only 5xx errors have an exception.
        if response.exception and self.raise_request_exception:
            raise response.exception

        if response.cookies:
            self.cookies.update(response.cookies)
        return response

    def get(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Make a GET request."""
        return self.request(
            method="GET",
            path=path,
            query_params=query_params,
            headers=headers,
            follow_redirects=follow_redirects,
            secure=secure,
        )

    def head(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Make a HEAD request."""
        return self.request(
            method="HEAD",
            path=path,
            query_params=query_params,
            headers=headers,
            follow_redirects=follow_redirects,
            secure=secure,
        )

    def options(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Make an OPTIONS request."""
        return self.request(
            method="OPTIONS",
            path=path,
            query_params=query_params,
            headers=headers,
            follow_redirects=follow_redirects,
            secure=secure,
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
        follow_redirects: bool = False,
        secure: bool = True,
    ) -> ClientResponse:
        """Make a POST request."""
        return self.request(
            method="POST",
            path=path,
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
        """Make a PUT request."""
        return self.request(
            method="PUT",
            path=path,
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
        """Make a PATCH request."""
        return self.request(
            method="PATCH",
            path=path,
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
        """Make a DELETE request."""
        return self.request(
            method="DELETE",
            path=path,
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
        lifecycle = self._handler.run_pipeline(request)
        returned_response = lifecycle.response
        if returned_response.cookies:
            self.cookies.update(returned_response.cookies)
        if not isinstance(returned_response, WebSocketResponse):
            body = lifecycle.read()
            status_code = lifecycle.sent_status_code
            assert status_code is not None
            raise WebSocketRejected(
                ClientResponse(
                    returned_response=returned_response,
                    request=request,
                    status_code=status_code,
                    body=body,
                )
            )
        return WebSocketTestConnection(lifecycle, request=request, timeout=timeout)

    def _follow_redirects(
        self,
        response: ClientResponse,
        *,
        body: bytes,
        content_type: str,
        headers: dict[str, str] | None,
    ) -> ClientResponse:
        """
        Follow redirect responses until a non-redirect response is reached.
        """
        redirect_chain: list[tuple[str, int]] = []
        while response.status_code in _REDIRECT_STATUS_CODES:
            response_url = response.redirect_to
            if response_url is None:
                break  # a 3xx without a Location header — nowhere to go
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
                    body=body,
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

            response = self._send(request)
            response._redirect_chain = redirect_chain

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

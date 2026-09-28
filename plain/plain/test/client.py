import json
import re
from http import HTTPStatus
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

from plain.http import Request, WebSocketResponse
from plain.server.inprocess import InProcessServer, SentResponse
from plain.urls import get_resolver
from plain.utils.http import urlencode

from .exceptions import RedirectCycleError, require_app
from .request_builder import (
    DEFAULT_PORTS,
    Target,
    build_encoded_request,
    encode_request_body,
    join_query_strings,
    split_target,
)

if TYPE_CHECKING:
    from plain.http import Response
    from plain.http.response import ResponseHeaders
    from plain.urls import ResolverMatch

    from .websocket import WebSocketTestConnection

__all__ = [
    "Client",
    "ClientResponse",
]


# Structured suffix spec: https://tools.ietf.org/html/rfc6838#section-4.2.8
_JSON_CONTENT_TYPE_RE = re.compile(r"^application\/(.+\+)?json")

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

    def __init__(self, sent: SentResponse):
        self._returned_response = sent.response
        self._request = sent.request
        self._status_code = sent.status_code
        self._body = sent.body
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
        `Client(raise_exceptions=False)` kept it from being raised."""
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


class Client:
    """
    A client for making requests against the app without running a server.

    It speaks the same vocabulary as the rest of Plain: `form_data=` arrives
    as `request.form_data`, `json_data=` as `request.json_data`, `files=` as
    `request.files`, and `query_params=` as `request.query_params`.

    A path makes a request to `https://testserver`. Pass a full URL when the
    scheme, host or port matter: `client.get("http://testserver/")`.

    Client objects are stateful — they keep the cookies (and so the session)
    that responses set, for the lifetime of the Client instance. `cookies` is
    that jar: logging a client in is writing the session cookie to it, which
    is what `plain.auth.test.login_client` does.

    `headers` are sent with every request. `raise_exceptions=False` keeps an
    exception the app raised as the 5xx response it became, on
    `response.exception`, where the default is to raise it from the request.
    """

    def __init__(
        self,
        *,
        raise_exceptions: bool = True,
        headers: dict[str, str] | None = None,
    ) -> None:
        require_app("Client")
        self.raise_exceptions = raise_exceptions
        self._headers: dict[str, str] = headers or {}
        self._cookies: SimpleCookie = SimpleCookie()
        self._server = InProcessServer()

    @property
    def cookies(self) -> SimpleCookie:
        """The cookies sent with every request, updated by every response."""
        return self._cookies

    def request(
        self,
        method: str,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        form_data: dict[str, Any] | None = None,
        json_data: Any = None,
        body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> ClientResponse:
        """Make a request with any method."""
        encoded_body, encoded_content_type = encode_request_body(
            form_data=form_data,
            json_data=json_data,
            body=body,
            files=files,
            content_type=content_type,
        )
        target = split_target(path)
        target.query_string = join_query_strings(
            target.query_string, urlencode(query_params or {}, doseq=True)
        )
        response = self._send(
            self._build_request(
                method,
                target,
                body=encoded_body,
                content_type=encoded_content_type,
                headers=headers,
            )
        )
        if follow_redirects:
            response = self._follow_redirects(
                response,
                body=encoded_body,
                content_type=encoded_content_type,
                headers=headers,
            )
        return response

    def _build_request(
        self,
        method: str,
        target: Target,
        *,
        body: bytes = b"",
        content_type: str = "",
        headers: dict[str, str] | None,
    ) -> Request:
        """Build a request as this client sends it: with the client's
        headers under the request's own, and the cookies in its jar."""
        all_headers: dict[str, str] = dict(self._headers)
        if headers:
            all_headers.update(headers)

        cookie_header = "; ".join(
            sorted(
                f"{morsel.key}={morsel.coded_value}"
                for morsel in self._cookies.values()
            )
        )
        if cookie_header:
            all_headers["Cookie"] = cookie_header

        return build_encoded_request(
            method,
            target.path,
            scheme=target.scheme,
            host=target.host,
            port=target.port,
            query_string=target.query_string,
            body=body,
            content_type=content_type,
            headers=all_headers,
        )

    def _send(self, request: Request) -> ClientResponse:
        """Run a Request through the app and wrap what came back."""
        response = ClientResponse(self._server.handle(request).send())

        # Only 5xx errors have an exception.
        if response.exception and self.raise_exceptions:
            raise response.exception

        if response.cookies:
            self._cookies.update(response.cookies)
        return response

    def get(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> ClientResponse:
        """Make a GET request."""
        return self.request(
            "GET",
            path,
            query_params=query_params,
            headers=headers,
            follow_redirects=follow_redirects,
        )

    def head(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> ClientResponse:
        """Make a HEAD request."""
        return self.request(
            "HEAD",
            path,
            query_params=query_params,
            headers=headers,
            follow_redirects=follow_redirects,
        )

    def options(
        self,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> ClientResponse:
        """Make an OPTIONS request."""
        return self.request(
            "OPTIONS",
            path,
            query_params=query_params,
            headers=headers,
            follow_redirects=follow_redirects,
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
    ) -> ClientResponse:
        """Make a POST request."""
        return self.request(
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
    ) -> ClientResponse:
        """Make a PUT request."""
        return self.request(
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
    ) -> ClientResponse:
        """Make a PATCH request."""
        return self.request(
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
    ) -> ClientResponse:
        """Make a DELETE request."""
        return self.request(
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
        )

    def websocket(
        self,
        path: str,
        *,
        subprotocols: tuple[str, ...] = (),
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
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

        target = split_target(path)
        target.query_string = join_query_strings(
            target.query_string, urlencode(query_params or {}, doseq=True)
        )
        request = self._build_request("GET", target, headers=handshake)

        handled = self._server.handle(request)
        if handled.response.cookies:
            self._cookies.update(handled.response.cookies)
        if not isinstance(handled.response, WebSocketResponse):
            raise WebSocketRejected(ClientResponse(handled.send()))
        return WebSocketTestConnection(handled, timeout=timeout)

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
            location = response.redirect_to
            if location is None:
                break  # a 3xx without a Location header — nowhere to go
            redirect_chain.append((location, response.status_code))

            previous = response.request
            target = _redirect_target(location, previous=previous)

            method = previous.method
            if response.status_code in (
                HTTPStatus.TEMPORARY_REDIRECT,
                HTTPStatus.PERMANENT_REDIRECT,
            ) and method not in ("GET", "HEAD"):
                # 307/308 preserve the request method and body.
                request = self._build_request(
                    method,
                    target,
                    body=body,
                    content_type=content_type,
                    headers=headers,
                )
            else:
                # Everything else redirects as a GET without a body.
                request = self._build_request(
                    "GET" if method not in ("GET", "HEAD") else method,
                    target,
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


def _redirect_target(location: str, *, previous: Request) -> Target:
    """Where a `Location` header leads, from the request that was redirected.

    As a browser resolves it: whatever the location leaves out is the
    previous request's. One that names a scheme or a host without a port
    goes to that scheme's port, not the previous request's.
    """
    url = urlsplit(location)

    scheme = url.scheme or previous.scheme
    host = url.hostname or previous.server_name
    if url.port:
        port = str(url.port)
    elif url.scheme or url.hostname:
        port = DEFAULT_PORTS.get(scheme, previous.server_port)
    else:
        port = previous.server_port

    path = url.path
    # RFC 3986 Section 6.2.3: Empty path should be normalized to "/".
    if not path and url.netloc:
        path = "/"
    # Prepend the request path to handle relative path redirects
    if not path.startswith("/"):
        path = urljoin(previous.path, path)

    return Target(
        scheme=scheme,
        host=host,
        port=port,
        path=path,
        query_string=url.query,
    )

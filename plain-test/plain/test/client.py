import functools
import json
import re
from collections.abc import Callable
from dataclasses import replace
from functools import cached_property
from http import HTTPStatus
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from plain.http import Request, WebSocketResponse
from plain.server.inprocess import HandledRequest, InProcessServer, SentResponse

from .exceptions import RedirectCycleError, require_app
from .request_builder import (
    Target,
    build_encoded_request,
    encode_request_body,
    split_target,
)
from .websocket import (
    DEFAULT_TIMEOUT,
    WebSocketRejected,
    WebSocketTestConnection,
    handshake_headers,
)

if TYPE_CHECKING:
    from plain.http import Response
    from plain.http.response import ResponseHeaders

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
        "returned_response",
    )

    def __init__(self, sent: SentResponse):
        self._sent = sent
        self._redirect_chain: list[tuple[str, int]] = []

    @property
    def status_code(self) -> int:
        """The status that went out — the view's, unless its streaming body
        failed before producing anything, which a server answers with 500."""
        return self._sent.status_code

    @property
    def headers(self) -> ResponseHeaders:
        """The response headers."""
        return self._sent.response.headers

    @property
    def cookies(self) -> SimpleCookie:
        """The cookies this response set."""
        return self._sent.response.cookies

    @property
    def body(self) -> bytes:
        """The body the response sent — for a streaming response too, read to
        the end the way a server sends it (empty for HEAD, 204, 304)."""
        return self._sent.body

    @property
    def text(self) -> str:
        """The body the response sent, decoded as a string."""
        return self._sent.body.decode(self._sent.response.charset)

    @cached_property
    def json_data(self) -> Any:
        """The body the response sent, parsed as JSON (requires a JSON content type)."""
        content_type = self.headers.get("Content-Type", "")
        if not _JSON_CONTENT_TYPE_RE.match(content_type):
            raise ValueError(
                f'Content-Type header is "{content_type}", not "application/json"'
            )
        return json.loads(self.text)

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
        """The request that produced this response. The route that handled
        it is `request.resolver_match`."""
        return self._sent.request

    @property
    def exception(self) -> Exception | None:
        """The exception behind a 5xx response, when
        `Client(raise_exceptions=False)` kept it from being raised."""
        return self._sent.response.exception

    @property
    def returned_response(self) -> Response:
        """The `Response` object the app returned.

        Everything else here describes what was sent. This is the object
        itself, for asserting on its type or on an attribute only that type
        has. Its own `content` and `status_code` can differ from what went
        out (a HEAD, a 204, a streaming body that failed).
        """
        return self._sent.response

    def __getattr__(self, name: str) -> Any:
        # Only reached for a name that isn't defined above.
        raise AttributeError(
            f"The test client's response has no `{name}`. It has: "
            + ", ".join(type(self)._NAMES)
            + ". The `Response` the app returned is `response.returned_response`."
        )

    def __repr__(self) -> str:
        return (
            f"<ClientResponse status_code={self._sent.status_code}"
            f" of {self._sent.response!r}>"
        )


def _takes_keywords_after_the_path[**P, R](
    verb: Callable[P, R],
) -> Callable[P, R]:
    """For the client's verbs: say which keyword, when data is passed by
    position.

    `client.post("/login", {"email": ...})` is how a test client is usually
    called, and here everything after the path is a keyword. Python's own
    message for it is "post() takes 2 positional arguments but 3 were
    given", which doesn't say what to write.

    The verbs keep the signatures they're written with. This only looks at
    how many arguments came by position.
    """

    @functools.wraps(verb)
    def checked(*args: P.args, **kwargs: P.kwargs) -> R:
        # The client itself, and the path.
        if len(args) > 2:
            # The verb's own name: `functools.wraps` gave it to this function.
            name = checked.__name__
            if name in ("get", "head", "options"):
                keywords = "`query_params=` for the query string"
                example = f'client.{name}("/path", query_params={{...}})'
            else:
                keywords = (
                    "`form_data=` for a form, `json_data=` for JSON, or"
                    " `body=` with `content_type=` for anything else"
                )
                example = f'client.{name}("/path", form_data={{...}})'
            raise TypeError(
                f"client.{name}() takes the path, and keywords after it."
                f" What was passed second goes in by name: {keywords}."
                f" For example: {example}"
            )
        return verb(*args, **kwargs)

    return checked


# Names a test client is often expected to have, and what to write here.
_WHAT_TO_WRITE_FOR = {
    "force_login": "`login_client(client, user)`, from plain.auth.test",
    "login": "`login_client(client, user)`, from plain.auth.test",
    "logout": "`logout_client(client)`, from plain.auth.test",
    "session": "`get_client_session(client)`, from plain.sessions.test",
    "trace": '`client.request("TRACE", path)`',
}


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

    def __getattr__(self, name: str) -> Any:
        # Only reached for a name the client doesn't have.
        what_to_write = _WHAT_TO_WRITE_FOR.get(name)
        if what_to_write is not None:
            raise AttributeError(
                f"The test client has no `{name}`. Write {what_to_write}."
            )
        raise AttributeError(
            f"The test client has no `{name}`. It makes requests (`get`,"
            " `head`, `options`, `post`, `put`, `patch`, `delete`,"
            " `request`, `websocket`) and keeps `cookies`."
        )

    def __repr__(self) -> str:
        # The cookies' names and not their values: a session key is a
        # credential, and this is printed in failure reports.
        return f"<Client cookies={sorted(self._cookies)}>"

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
        response = self._send(
            self._build_request(
                method,
                split_target(path, query_params=query_params),
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
            target,
            body=body,
            content_type=content_type,
            headers=all_headers,
        )

    def _handle(self, request: Request) -> HandledRequest:
        """Run a request through the app, and keep the cookies it set.

        Every request this client makes comes through here, a websocket's
        handshake included.
        """
        handled = self._server.handle(request)
        if handled.response.cookies:
            self._cookies.update(handled.response.cookies)
        return handled

    def _sent(self, handled: HandledRequest) -> ClientResponse:
        """Send a handled request's response and wrap what went out.

        An exception the app raised is raised from here, after the response
        is sent and closed, unless `raise_exceptions` is off. Only a 5xx
        has one.
        """
        response = ClientResponse(handled.send())
        if response.exception and self.raise_exceptions:
            raise response.exception
        return response

    def _send(self, request: Request) -> ClientResponse:
        """Run a Request through the app and wrap what came back."""
        return self._sent(self._handle(request))

    @_takes_keywords_after_the_path
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

    @_takes_keywords_after_the_path
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

    @_takes_keywords_after_the_path
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

    @_takes_keywords_after_the_path
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

    @_takes_keywords_after_the_path
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

    @_takes_keywords_after_the_path
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

    @_takes_keywords_after_the_path
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
        timeout: float = DEFAULT_TIMEOUT,
    ) -> WebSocketTestConnection:
        """Open a websocket to `path` and drive the view's `websocket()` in-process.

            with client.websocket("/live/", subprotocols=("binary",)) as ws:
                ws.send(b"...")
                assert ws.receive() == b"..."

        The handshake runs through the normal pipeline with this client's
        cookies, so auth applies. A response other than the 101 raises
        `WebSocketRejected` carrying it, and a handshake the app raised from
        raises that exception, as any other request does. Every call on the
        connection has a timeout (default 5 s) and raises `TimeoutError`
        when it elapses.
        """
        handshake = handshake_headers(subprotocols=subprotocols)
        if headers:
            handshake.update(headers)

        handled = self._handle(
            self._build_request(
                "GET",
                split_target(path, query_params=query_params),
                headers=handshake,
            )
        )
        if isinstance(handled.response, WebSocketResponse):
            return WebSocketTestConnection(handled, timeout=timeout)
        raise WebSocketRejected(self._sent(handled))

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
    previous_url = (
        f"{previous.scheme}://{previous.server_name}:{previous.server_port}"
        f"{previous.path}"
    )
    target = split_target(urljoin(previous_url, location))
    if not target.path:
        # RFC 3986 Section 6.2.3: Empty path should be normalized to "/".
        return replace(target, path="/")
    return target

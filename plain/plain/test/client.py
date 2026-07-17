from __future__ import annotations

import asyncio
import json
from http import HTTPStatus
from http.cookies import SimpleCookie
from io import BytesIO, IOBase
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse, urlsplit

from plain.http import AsyncStreamingResponse, Request, StreamingResponse
from plain.http import Response as HttpResponse
from plain.internal.handlers.base import BaseHandler
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

__all__ = [
    "Client",
    "ClientResponse",
    "RequestFactory",
]


_BOUNDARY = "BoUnDaRyStRiNg"
_MULTIPART_CONTENT = f"multipart/form-data; boundary={_BOUNDARY}"
# Structured suffix spec: https://tools.ietf.org/html/rfc6838#section-4.2.8
_JSON_CONTENT_TYPE_RE = _lazy_re_compile(r"^application\/(.+\+)?json")

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
        response: Response,
        client: Client,
    ):
        self._response = response
        self._json_cache: Any = None
        # Test-specific attributes
        self.client = client
        self.request: Request
        self.redirect_chain: list[tuple[str, int]]
        self.resolver_match: SimpleLazyObject | ResolverMatch

    @property
    def text(self) -> str:
        """Response content decoded as a string."""
        return self._response.content.decode(self._response.charset)

    @property
    def body(self) -> bytes:
        """Raw response content."""
        return self._response.content

    @property
    def json_data(self) -> Any:
        """Response content parsed as JSON (requires a JSON content type)."""
        if self._json_cache is None:
            content_type = self._response.headers.get("Content-Type", "")
            if not _JSON_CONTENT_TYPE_RE.match(content_type):
                raise ValueError(
                    f'Content-Type header is "{content_type}", not "application/json"'
                )
            self._json_cache = json.loads(
                self._response.content.decode(self._response.charset)
            )
        return self._json_cache

    @property
    def redirect_to(self) -> str | None:
        """The redirect target if this is a 3xx response, otherwise None."""
        if 300 <= self._response.status_code < 400:
            return self._response.headers.get("Location")
        return None

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the wrapped response."""
        return getattr(self.__dict__["_response"], name)

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


def _conditional_content_removal(request: Request, response: Response) -> Response:
    """
    Simulate the behavior of most web servers by removing the content of
    responses for HEAD requests, 1xx, 204, and 304 responses. Ensure
    compliance with RFC 9112 Section 6.3.
    """
    should_strip = (
        100 <= response.status_code < 200
        or response.status_code in (204, 304)
        or request.method == "HEAD"
    )
    if should_strip:
        if isinstance(response, StreamingResponse):
            response.streaming_content = iter([])
        elif not response.streaming:
            response.content = b""
    return response


class ClientHandler(BaseHandler):
    """
    An HTTP Handler that can be used for testing purposes. Takes a Request
    object directly and returns the raw Response with the originating
    Request attached to its ``request`` attribute.
    """

    def __call__(self, request: Request) -> Response:
        # Set up middleware if needed. We couldn't do this earlier, because
        # settings weren't available.
        if self._middleware_chain is None:
            self.load_middleware()

        from plain.internal.handlers.base import _AsyncViewPending

        with self._start_request_span(request) as span:
            # Call the sync pipeline directly — no event loop needed for sync
            # views. This keeps the test client usable from both sync tests and
            # async tests (where asyncio.run() would raise).
            result = self._run_sync_pipeline(request)

            if isinstance(result, _AsyncViewPending):
                response = self._handle_async_view(request, result)
            else:
                response = result

            # Collect async streaming content so tests can use response.content.
            if isinstance(response, AsyncStreamingResponse):
                response = self._collect_async_streaming(response)

            self._finalize_span(span, response)

        response._resource_closers.append(request.close)

        # Simulate behaviors of most web servers.
        _conditional_content_removal(request, response)

        # Attach the originating request to the response so that it could be
        # later retrieved.
        setattr(response, "request", request)

        # Emulate a server by calling the close method on completion.
        response.close()

        return response

    def _collect_async_streaming(self, response: AsyncStreamingResponse) -> Response:
        """Collect async streaming content into a regular Response for tests."""

        async def _collect(resp: AsyncStreamingResponse) -> HttpResponse:
            chunks = []
            async for chunk in resp:
                chunks.append(chunk)
            collected = b"".join(chunks)

            sync_response = HttpResponse(
                collected,
                status_code=resp.status_code,
                content_type=resp.headers.get("Content-Type"),
            )
            for key, value in resp.headers.items():
                if key != "Content-Type":
                    sync_response.headers[key] = value
            sync_response.cookies = resp.cookies
            sync_response._resource_closers = resp._resource_closers
            resp._resource_closers = []
            await resp.aclose()
            return sync_response

        return asyncio.run(_collect(response))

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
        raise TypeError(
            "content_type only applies to a raw body — form_data and json_data set their own"
        )

    if json_data is not None:
        return (
            json.dumps(json_data, cls=json_encoder).encode(),
            "application/json",
        )

    if body is not None:
        return (
            force_bytes(body),
            content_type or "application/octet-stream",
        )

    if form_data is not None or files is not None:
        merged: dict[str, Any] = dict(form_data or {})
        merged.update(files or {})
        return (
            encode_multipart(_BOUNDARY, merged),
            _MULTIPART_CONTENT,
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

        # Add content headers when there's a body
        if data:
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

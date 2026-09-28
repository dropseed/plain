"""Handling a request in-process: the app, with no socket.

    server = InProcessServer()
    sent = server.handle(request).send()

The server handles a request in two steps. The handler runs the pipeline
(middleware, then the view) and returns a response that hasn't gone
anywhere yet. Then the response is sent, or, for an accepted websocket
upgrade, the socket is served. `InProcessServer` does the same two steps on
the calling thread, with the same handler and the same `ResponseLifecycle`
the protocol writers drive, so what it reports is what a client would have
received.
"""

import asyncio
import socket
from dataclasses import dataclass

from plain.http import Request, Response, WebSocketResponse, content_length_forbidden
from plain.internal.handlers.base import BaseHandler
from plain.internal.handlers.response_lifecycle import ResponseLifecycle

from .connection import Connection
from .http.websocket import run_websocket

__all__ = ["HandledRequest", "InProcessServer", "SentResponse"]


@dataclass(frozen=True)
class SentResponse:
    """What went out for one request."""

    request: Request
    # The `Response` the app returned. Its own `status_code` and `content`
    # can differ from what was sent: a HEAD or a 204 sends no body, and a
    # streaming body that fails before its first chunk is answered with a 500.
    response: Response
    # The status that was sent.
    status_code: int
    # The bytes that were sent. A streaming body is read to its end.
    body: bytes


class HandledRequest:
    """A request the pipeline has run, whose response hasn't been sent.

    `response` is what the app returned. Either `send()` it, or, when it is
    a `WebSocketResponse`, `serve_websocket()`. One or the other, once.
    """

    def __init__(self, lifecycle: ResponseLifecycle) -> None:
        self._lifecycle = lifecycle
        self._finished_by: str | None = None

    @property
    def request(self) -> Request:
        return self._lifecycle.request

    @property
    def response(self) -> Response:
        return self._lifecycle.response

    def send(self) -> SentResponse:
        """Read the body on this thread, close the response, and report
        what was sent.

        The body runs where the pipeline ran: in the caller's context, with
        the request span current. A body that raises partway is handled as
        a server handles it. It is logged, recorded on the span, and set as
        `response.exception`, and the chunks before it are what was sent.
        """
        self._finish_by("send()")
        body = self._lifecycle.read()

        response = self._lifecycle.response
        # A status that can't carry Content-Length (1xx, 204) loses it, as
        # the protocol writers drop it on the way out. HEAD and 304 keep
        # theirs: it describes the body a GET would have had.
        if content_length_forbidden(response.status_code):
            del response.headers["Content-Length"]

        # read() always settles a status. None is for a server whose client
        # left before anything went out.
        status_code = self._lifecycle.sent_status_code
        assert status_code is not None

        return SentResponse(
            request=self._lifecycle.request,
            response=response,
            status_code=status_code,
            body=body,
        )

    async def serve_websocket(
        self, sock: socket.socket, *, close_timeout: float = 1.0
    ) -> BaseException | None:
        """Serve the accepted websocket over `sock` until it ends.

        `sock` is the server's end of a connected pair
        (`socket.socketpair()`); the caller keeps the other end and speaks
        the client's side of the protocol over it. This is the code the
        server runs once it has written the 101, so the view's
        `websocket()` runs as it does in production, in the context the
        handshake ran in.

        Returns the view's exception if it failed with something other
        than the socket ending, after logging it, and `None` otherwise.
        """
        if not isinstance(self.response, WebSocketResponse):
            raise TypeError(
                "The app didn't accept a websocket: it answered with a"
                f" {type(self.response).__name__}"
                f" ({self.response.status_code}). Send that with send()."
            )
        self._finish_by("serve_websocket()")

        loop = asyncio.get_running_loop()
        reader, writer = await asyncio.open_connection(sock=sock)
        connection = Connection(
            None,
            reader,
            writer,
            (self.request.remote_addr, 0),
            (self.request.server_name, int(self.request.server_port or 0)),
        )
        return await run_websocket(
            self._lifecycle,
            connection,
            # Completes when a worker starts draining. Nothing drains here.
            shutdown_wait=loop.create_future(),
            close_timeout=lambda: close_timeout,
        )

    def _finish_by(self, method: str) -> None:
        if self._finished_by is not None:
            raise RuntimeError(
                f"This request was already finished by {self._finished_by}."
                " A handled request is sent, or served as a websocket, once."
            )
        self._finished_by = method


class InProcessServer:
    """Handles requests on the calling thread.

    It loads the app's middleware at the first request and keeps it, as a
    server's worker does. Create a new one to pick up a changed
    `MIDDLEWARE` setting.
    """

    def __init__(self) -> None:
        self._handler = BaseHandler()

    def handle(self, request: Request) -> HandledRequest:
        """Run `request` through middleware and the view.

        An exception the app raises becomes its error response, as it does
        under a server, with the exception on `response.exception`.
        """
        return HandledRequest(self._handler.handle_in_process(request))

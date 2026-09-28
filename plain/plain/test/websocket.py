"""Driving a view's `websocket()` in-process from a test.

    with client.websocket("/live/") as ws:
        ws.send("hello")
        assert ws.receive() == "hello"

The handshake runs through the same pipeline as any test-client request.
On acceptance the view's coroutine is served by the same code the server
uses, over a socketpair, on an event loop this object owns and steps from
the test's own thread whenever it is asked to send, receive, or close.
No background thread: the view runs on the test thread, inside a copy of
the test's context, so the test database transaction is visible to it.
"""

import asyncio
import base64
import os
import socket
from types import TracebackType
from typing import Any, Self

from plain.http import Response, WebSocketClosed, WebSocketResponse
from plain.http.websocket_frames import (
    OP_BINARY,
    OP_CLOSE,
    OP_CONTINUATION,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    IncompleteFrame,
    encode_close,
    encode_frame,
    parse_close_payload,
    read_frame,
)
from plain.internal.handlers.response_lifecycle import ResponseLifecycle
from plain.server.connection import Connection
from plain.server.http.websocket import run_websocket

DEFAULT_TIMEOUT = 5.0

# Server-to-client frames are read without a size cap: the test wrote the
# view and knows what it sends.
_NO_CAP = 1 << 40


def handshake_headers(
    *, key: str | None = None, subprotocols: tuple[str, ...] = ()
) -> dict[str, str]:
    """The request headers of a well-formed RFC 6455 opening handshake.

    A fresh random key unless one is given (tests pin the RFC's example
    key to assert on the accept value).
    """
    headers = {
        "Upgrade": "websocket",
        "Connection": "Upgrade",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": key or base64.b64encode(os.urandom(16)).decode(),
    }
    if subprotocols:
        headers["Sec-WebSocket-Protocol"] = ", ".join(subprotocols)
    return headers


def _client_frame(opcode: int, payload: bytes = b"") -> bytes:
    """One client-to-server frame, masked with a fresh key as RFC 6455 requires."""
    return encode_frame(opcode, payload, mask=os.urandom(4))


class WebSocketRejected(Exception):
    """The upgrade did not produce a socket; `.response` says why (a 403, a redirect)."""

    def __init__(self, response: Response) -> None:
        self.response = response
        super().__init__(f"WebSocket upgrade rejected with {response.status_code}")


class WebSocketTestConnection:
    """The client end of an accepted websocket, driven synchronously."""

    def __init__(
        self, lifecycle: ResponseLifecycle, *, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        response = lifecycle.response
        assert isinstance(response, WebSocketResponse)
        self.response = response
        self.subprotocol = response.subprotocol
        self._timeout = timeout
        self._closed = False

        self._loop = asyncio.new_event_loop()
        try:
            server_sock, client_sock = socket.socketpair()
            self._reader, self._writer, conn = self._loop.run_until_complete(
                self._open_pair(server_sock, client_sock)
            )
        except BaseException:
            self._loop.run_until_complete(self._settle_transports())
            self._loop.close()
            raise
        # `lifecycle.context` is the copy of the test's context that
        # `ClientHandler.run_pipeline()` took after the handshake: the view
        # sees what the test set up (the `db` fixture's transaction
        # included), with the handshake's request span current.
        self._server_task = self._loop.create_task(
            run_websocket(
                lifecycle,
                conn,
                shutdown_wait=self._loop.create_future(),
                close_timeout=lambda: 1.0,
            )
        )

    async def _settle_transports(self) -> None:
        """Let asyncio finish closing both ends before the loop goes away."""
        try:
            await asyncio.wait_for(self._writer.wait_closed(), 1)
        except TimeoutError, OSError, AttributeError:
            pass
        await asyncio.sleep(0)

    @staticmethod
    async def _open_pair(
        server_sock: socket.socket, client_sock: socket.socket
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, Connection]:
        server_reader, server_writer = await asyncio.open_connection(sock=server_sock)
        client_reader, client_writer = await asyncio.open_connection(sock=client_sock)
        conn = Connection(
            None,  # ty: ignore[invalid-argument-type]
            server_reader,
            server_writer,
            ("127.0.0.1", 0),
            ("testserver", 443),
        )
        return client_reader, client_writer, conn

    # ------------------------------------------------------------------

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if not self._closed:
                self.close()
        finally:
            self._writer.close()
            self._loop.run_until_complete(self._settle_transports())
            self._loop.close()
        if exc is None:
            self._raise_view_error()

    def send(self, message: str | bytes, *, timeout: float | None = None) -> None:
        """Send one message to the view."""
        if isinstance(message, str):
            frame = _client_frame(OP_TEXT, message.encode())
        else:
            frame = _client_frame(OP_BINARY, bytes(message))
        self._writer.write(frame)
        self._step(self._writer.drain(), timeout)

    def receive(self, *, timeout: float | None = None) -> str | bytes:
        """The next message the view sent.

        Raises the view's own exception if it failed, `WebSocketClosed` if
        it closed the socket, and `TimeoutError` if nothing arrives.
        """
        return self._step(self._read_message(), timeout)

    def close(
        self, code: int = 1000, reason: str = "", *, timeout: float | None = None
    ) -> None:
        """Close from the client side and wait for the view to finish."""
        if self._closed:
            return
        self._closed = True
        self._writer.write(encode_close(code, reason, mask=os.urandom(4)))
        try:
            self._step(self._writer.drain(), timeout)
            self._step(asyncio.shield(self._server_task), timeout)
        except TimeoutError, OSError:
            # A view that never reads the socket does not see the CLOSE;
            # stop it the way a worker shutdown would.
            self._server_task.cancel()
            self._loop.run_until_complete(
                asyncio.gather(self._server_task, return_exceptions=True)
            )

    # ------------------------------------------------------------------

    def _step(self, awaitable: Any, timeout: float | None) -> Any:
        return self._loop.run_until_complete(
            asyncio.wait_for(awaitable, self._timeout if timeout is None else timeout)
        )

    def _raise_view_error(self) -> None:
        if not self._server_task.done() or self._server_task.cancelled():
            return
        # Two different failures: the serving code itself blew up, or the
        # view failed and `run_websocket` logged it and returned it.
        if (exc := self._server_task.exception()) is not None:
            raise exc
        if (view_error := self._server_task.result()) is not None:
            raise view_error

    async def _read_message(self) -> str | bytes:
        fragments: list[bytes] = []
        text = False
        while True:
            if self._server_task.done():
                self._raise_view_error()
            try:
                frame = await read_frame(self._reader.read, _NO_CAP, require_mask=False)
            except IncompleteFrame:
                # The server closed the transport — after a CLOSE we already
                # surfaced, or because the view failed.
                await asyncio.gather(self._server_task, return_exceptions=True)
                self._raise_view_error()
                raise WebSocketClosed() from None

            if frame.opcode == OP_PING:
                self._writer.write(_client_frame(OP_PONG, frame.payload))
                continue
            if frame.opcode == OP_PONG:
                continue
            if frame.opcode == OP_CLOSE:
                reason = parse_close_payload(frame.payload)
                self._writer.write(_client_frame(OP_CLOSE, frame.payload))
                self._closed = True
                await asyncio.gather(self._server_task, return_exceptions=True)
                self._raise_view_error()
                raise WebSocketClosed(reason.code, reason.reason)

            if frame.opcode == OP_TEXT:
                text = True
            fragments.append(frame.payload)
            if frame.fin:
                payload = b"".join(fragments)
                return payload.decode() if text else payload
            if frame.opcode != OP_CONTINUATION and len(fragments) > 1:
                raise AssertionError("server interleaved two messages")

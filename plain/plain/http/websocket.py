"""WebSockets: the accept response, upgrade detection, and the `ws` a view holds.

A websocket is an ordinary `View` with an `async def websocket(self, ws)`
handler. The request runs through the normal pipeline (middleware,
`before_request`, URL kwargs), so auth is inherited; the view then
returns a `WebSocketResponse`, which the server frames as a bodiless
101 before handing the raw connection to a `WebSocket` and running the
view's coroutine for the life of the socket.

`WebSocket` is the whole surface a view sees:

    async for message in ws     # str or bytes; ends quietly on any close
    await ws.send(str | bytes)  # raises WebSocketClosed once closed
    await ws.close(code=1000, reason="")
    ws.subprotocol              # the negotiated one, or None

Framing is in `websocket_frames`; this module is the message layer on
top of it: fragment reassembly, control frames, the close handshake,
the keepalive ping loop, and the size cap — plus the handshake pieces
(upgrade detection, subprotocol selection, the accept response).
"""

import asyncio
import base64
from collections.abc import Callable, Coroutine
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol, Self

from .response import Response
from .websocket_frames import (
    CLOSE_ABNORMAL,
    CLOSE_GOING_AWAY,
    CLOSE_INVALID_PAYLOAD,
    CLOSE_MESSAGE_TOO_BIG,
    CLOSE_NO_STATUS,
    CLOSE_NORMAL,
    CLOSE_POLICY_VIOLATION,
    CLOSE_PROTOCOL_ERROR,
    OP_BINARY,
    OP_CLOSE,
    OP_CONTINUATION,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    IncompleteFrame,
    PayloadTooLarge,
    ProtocolError,
    compute_accept_key,
    encode_close,
    encode_frame,
    parse_close_payload,
    read_frame,
)

if TYPE_CHECKING:
    from .request import Request

# Keepalive: a PING every PING_INTERVAL seconds, and the socket is failed
# with 1001 when no PONG arrives within PING_TIMEOUT of it. The same
# defaults as the `websockets` library, and well inside the 55 seconds a
# router like Heroku's allows a connection to sit idle.
PING_INTERVAL = 20.0
PING_TIMEOUT = 20.0

# How long `close()` waits for the peer to answer our CLOSE frame before
# closing the transport anyway. The server tightens this during drain.
CLOSE_TIMEOUT = 5.0

# Outbound frames go to the transport in chunks of this size, and each
# chunk gets WRITE_TIMEOUT to reach the kernel's send buffer. A live peer
# drains its receive window in milliseconds, however slow its link; one
# that has stopped reading never does, and without a bound a `send` would
# sit in `drain()` holding the write lock, keeping the keepalive from ever
# closing the socket. Chunking makes the bound "no progress for this
# long" rather than "the whole message within this long".
WRITE_CHUNK = 64 * 1024
WRITE_TIMEOUT = PING_TIMEOUT

# Messages the reader may hold for a view that is not iterating yet.
# Bounded so a push-only view (one that only ever sends) cannot make the
# reader buffer without limit; PING/PONG keep flowing while there is room.
RECEIVE_QUEUE_SIZE = 16


class WebSocketTransport(Protocol):
    """What `WebSocket` needs from the connection underneath it.

    The server's `Connection` satisfies this as-is; the test client
    supplies the same class over its end of a socketpair.
    """

    async def recv(self, n: int) -> bytes: ...

    async def sendall(self, data: bytes) -> None: ...

    def close(self) -> None: ...

    def abort(self) -> None: ...


class WebSocketClosed(Exception):
    """The socket is closed: raised by `send()` once no more frames can go out.

    A closed peer is a normal ending, not an error — a view that keeps
    sending after the browser left sees this and stops.
    """

    def __init__(self, code: int = CLOSE_ABNORMAL, reason: str = "") -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"WebSocket closed ({code}) {reason}".rstrip())


class WebSocket:
    """One open websocket, from the 101 to the transport close.

    The server enters it (`async with ws:` starts the reader and the
    keepalive pings, leaving it stops them) and hands it to the view,
    which iterates it, sends on it, and may close it.
    """

    def __init__(
        self,
        transport: WebSocketTransport,
        *,
        subprotocol: str | None = None,
        max_message_size: int,
        ping_interval: float = PING_INTERVAL,
        ping_timeout: float = PING_TIMEOUT,
    ) -> None:
        self._transport = transport
        self.subprotocol = subprotocol
        self._max_message_size = max_message_size
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout

        # Complete messages for the view. `_activity` wakes an iterator
        # blocked on an empty queue when a message lands or the socket ends.
        self._messages: asyncio.Queue[str | bytes] = asyncio.Queue(
            maxsize=RECEIVE_QUEUE_SIZE
        )
        self._activity = asyncio.Event()
        self._write_lock = asyncio.Lock()

        # Set once the socket is over, whichever side ended it and however:
        # the peer's CLOSE, ours timing out, a failure, or shutdown.
        self._closed = asyncio.Event()
        # Our CLOSE frame has gone out (or failed to). Between that and
        # `_closed` being set, `send` must already refuse and report the
        # code we sent, which is why `_send_close` records it too.
        self._close_sent = False
        self._close_code = CLOSE_ABNORMAL
        self._close_reason = ""
        self._pong_received = asyncio.Event()
        # True while the reader is parked on a full receive queue: the
        # view has stopped iterating, so nothing more (PONGs included) is
        # being read. A ping timeout in that state is the view's doing,
        # not the peer's, and is reported as such.
        self._receive_full = False

        self._reader_task: asyncio.Task[None] | None = None
        self._ping_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # The view-facing surface
    # ------------------------------------------------------------------

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    @property
    def close_code(self) -> int:
        """The close code once `closed`; 1006 when the socket ended without a CLOSE frame."""
        return self._close_code

    @property
    def close_reason(self) -> str:
        return self._close_reason

    async def wait_closed(self) -> None:
        """Block until the socket is over, however it ends."""
        await self._closed.wait()

    def __aiter__(self) -> WebSocket:
        return self

    async def __anext__(self) -> str | bytes:
        while True:
            try:
                return self._messages.get_nowait()
            except asyncio.QueueEmpty:
                pass
            if self.closed:
                raise StopAsyncIteration
            self._activity.clear()
            await self._activity.wait()

    async def send(self, message: str | bytes) -> None:
        if self.closed or self._close_sent:
            raise WebSocketClosed(self._close_code, self._close_reason)
        if isinstance(message, str):
            opcode, payload = OP_TEXT, message.encode()
        elif isinstance(message, bytes | bytearray | memoryview):
            opcode, payload = OP_BINARY, bytes(message)
        else:
            raise TypeError(
                f"WebSocket messages are str or bytes, not {type(message).__name__}"
            )
        try:
            await self._write(encode_frame(opcode, payload))
        except OSError:
            self._end(CLOSE_ABNORMAL)
            raise WebSocketClosed(self._close_code, self._close_reason) from None

    async def close(
        self,
        code: int = CLOSE_NORMAL,
        reason: str = "",
        *,
        timeout: float = CLOSE_TIMEOUT,
    ) -> None:
        """Start the closing handshake and finish it within `timeout`.

        Sends our CLOSE once, waits for the peer's (the reader answers
        it), then closes the transport. Safe to call more than once and
        from a task other than the one iterating.
        """
        if self.closed:
            return
        try:
            if not self._close_sent:
                await asyncio.wait_for(self._send_close(code, reason), timeout)
            await asyncio.wait_for(self._closed.wait(), timeout)
        except TimeoutError:
            pass
        self._end(code, reason)

    # ------------------------------------------------------------------
    # Server-facing lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Self:
        """Begin reading frames and pinging. Entered once, after the 101."""
        self._reader_task = asyncio.create_task(self._read_loop())
        self._ping_task = asyncio.create_task(self._ping_loop())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop the background tasks and make sure the transport is closed."""
        self._end()
        tasks = [t for t in (self._ping_task, self._reader_task) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _write(self, data: bytes) -> None:
        async with self._write_lock:
            complete = False
            try:
                for start in range(0, max(len(data), 1), WRITE_CHUNK):
                    await asyncio.wait_for(
                        self._transport.sendall(data[start : start + WRITE_CHUNK]),
                        WRITE_TIMEOUT,
                    )
                complete = True
            except TimeoutError:
                # The peer stopped reading. Abort rather than close: a
                # close would wait for the same buffer to flush.
                self._transport.abort()
                raise ConnectionResetError("Peer stopped reading") from None
            except asyncio.CancelledError:
                if self.closed:
                    # Teardown cancelled a writer the peer never drained;
                    # a close would hang on it.
                    self._transport.abort()
                elif len(data) > WRITE_CHUNK and not complete:
                    # A frame that was queued in pieces is now missing its
                    # tail; anything sent after it would be read as payload.
                    # A single-chunk frame is queued atomically and is fine.
                    self._transport.abort()
                    self._end(CLOSE_ABNORMAL)
                raise

    async def _send_close(self, code: int, reason: str) -> None:
        if self._close_sent:
            return
        self._close_sent = True
        self._close_code = code
        self._close_reason = reason
        try:
            await self._write(encode_close(code, reason))
        except OSError:
            self._end(CLOSE_ABNORMAL)

    def _end(self, code: int | None = None, reason: str = "") -> None:
        """The socket is over: record why (if told), wake everyone, drop the transport."""
        if self.closed:
            return
        if code is not None:
            self._close_code = code
            self._close_reason = reason
        self._closed.set()
        self._activity.set()
        try:
            # A close flushes what is queued. The paths that know the peer
            # has stopped draining (a write timeout, a CLOSE that could not
            # go out, a teardown cancel of a writer still holding the lock)
            # abort the transport themselves.
            self._transport.close()
        except OSError:
            pass

    async def _fail(self, code: int, reason: str) -> None:
        """Fail the connection (RFC 6455 §7.1.7): a best-effort CLOSE, then drop it.

        Never waits on a stuck writer: the CLOSE gets `CLOSE_TIMEOUT` to go
        out behind whatever holds the write lock, then the socket ends
        regardless.
        """
        try:
            await asyncio.wait_for(self._send_close(code, reason), CLOSE_TIMEOUT)
        except TimeoutError:
            # A 125-byte frame that cannot go out in that long is stuck
            # behind a writer the peer is not draining.
            self._transport.abort()
        self._end(code, reason)

    async def _read_loop(self) -> None:
        fragment_opcode: int | None = None
        fragment = bytearray()
        try:
            while not self.closed:
                frame = await read_frame(self._transport.recv, self._max_message_size)
                opcode = frame.opcode

                if opcode == OP_PING:
                    await self._write(encode_frame(OP_PONG, frame.payload))
                    continue
                if opcode == OP_PONG:
                    self._pong_received.set()
                    continue
                if opcode == OP_CLOSE:
                    peer = parse_close_payload(frame.payload)
                    echo = CLOSE_NORMAL if peer.code == CLOSE_NO_STATUS else peer.code
                    await self._send_close(echo, "")
                    self._end(peer.code, peer.reason)
                    return

                if opcode == OP_CONTINUATION:
                    if fragment_opcode is None:
                        raise ProtocolError("Continuation frame without a message")
                    fragment += frame.payload
                elif opcode in (OP_TEXT, OP_BINARY):
                    if fragment_opcode is not None:
                        raise ProtocolError("New message inside a fragmented one")
                    fragment_opcode = opcode
                    fragment = bytearray(frame.payload)
                else:
                    raise ProtocolError(f"Unexpected opcode {opcode:#x}")

                if len(fragment) > self._max_message_size:
                    raise PayloadTooLarge(len(fragment), self._max_message_size)

                if frame.fin:
                    payload = bytes(fragment)
                    message: str | bytes
                    if fragment_opcode == OP_TEXT:
                        message = payload.decode()
                    else:
                        message = payload
                    fragment_opcode = None
                    fragment = bytearray()
                    if self._messages.full():
                        self._receive_full = True
                    await self._messages.put(message)
                    self._receive_full = False
                    self._activity.set()
        except PayloadTooLarge:
            await self._fail(CLOSE_MESSAGE_TOO_BIG, "Message too big")
        except UnicodeDecodeError:
            await self._fail(CLOSE_INVALID_PAYLOAD, "Invalid UTF-8")
        except ProtocolError as exc:
            await self._fail(CLOSE_PROTOCOL_ERROR, str(exc))
        except IncompleteFrame, OSError:
            # The peer went away without a CLOSE — an abnormal close
            # (the default code) from our side, and a perfectly normal
            # ending for the view. The finally records it.
            pass
        finally:
            self._end()

    async def _ping_loop(self) -> None:
        while not self.closed:
            await asyncio.sleep(self._ping_interval)
            if self.closed:
                return
            self._pong_received.clear()
            try:
                # Bounded too: a `send` stuck on a dead peer holds the write
                # lock, and the keepalive must not queue behind it.
                await asyncio.wait_for(
                    self._write(encode_frame(OP_PING, b"")), self._ping_timeout
                )
                await asyncio.wait_for(self._pong_received.wait(), self._ping_timeout)
            except TimeoutError:
                # Before OSError: the builtin TimeoutError is an OSError.
                if self._receive_full:
                    await self._fail(
                        CLOSE_POLICY_VIOLATION,
                        "Receive buffer full: the handler stopped reading",
                    )
                else:
                    await self._fail(CLOSE_GOING_AWAY, "Ping timeout")
                return
            except OSError:
                self._end(CLOSE_ABNORMAL)
                return


class WebSocketResponse(Response):
    """The accepted upgrade: a bodiless 101 the framework constructs for a view.

    It flows through `after_response` like any response (so middleware
    cookies and headers land on the 101), and the server, on seeing it,
    frames the header block, opens a `WebSocket` on the connection and
    runs `handler(ws)` — the view's `websocket()` — until the socket
    ends, when its resource closers run. It is not a streaming response:
    no view code has run when middleware sees it, so anything a
    middleware releases at the end of an ordinary request can be released
    here too and re-acquired inside the socket. Application code never
    builds one; `Response` refuses 1xx status codes from callers, and
    this class is the framework's own 101.
    """

    _default_status_code = 101

    def __init__(
        self,
        *,
        request: Request,
        handler: Callable[[WebSocket], Coroutine[Any, Any, None]],
        subprotocol: str | None,
        max_message_size: int,
    ) -> None:
        super().__init__()
        self.request = request
        self.handler = handler
        self.subprotocol = subprotocol
        self.max_message_size = max_message_size

        self.headers["Sec-WebSocket-Accept"] = compute_accept_key(
            request.headers["Sec-WebSocket-Key"].strip()
        )
        if subprotocol:
            self.headers["Sec-WebSocket-Protocol"] = subprotocol


def is_websocket_upgrade(request: Request) -> bool:
    """True for a well-formed RFC 6455 opening handshake, else an ordinary GET.

    Anything short of the full set — wrong method, missing `Upgrade`,
    a `Connection` without the `upgrade` token, a version other than 13,
    a key that is not 16 base64 bytes — is served as a normal GET; the
    browser then fails the socket on its own. (The RFC's 426 for other
    versions is deliberately not implemented.)
    """
    if request.method != "GET":
        return False
    if request.headers.get("Upgrade", "").strip().lower() != "websocket":
        return False
    connection_tokens = {
        token.strip().lower()
        for token in request.headers.get("Connection", "").split(",")
    }
    if "upgrade" not in connection_tokens:
        return False
    if request.headers.get("Sec-WebSocket-Version", "").strip() != "13":
        return False
    key = request.headers.get("Sec-WebSocket-Key", "").strip()
    try:
        return len(base64.b64decode(key, validate=True)) == 16
    except ValueError:
        return False


def select_subprotocol(
    offered_header: str | None, supported: tuple[str, ...]
) -> str | None:
    """Pick the subprotocol to echo back, or None to echo nothing.

    `offered_header` is the request's `Sec-WebSocket-Protocol` value; repeated
    header lines arrive comma-joined. The client's order is the client's
    preference order (RFC 6455 Section 4.1), so the first offered name that we
    support wins even if `supported` lists another one first. Subprotocol names
    are tokens and compare case-sensitively.
    """
    if not offered_header:
        return None
    for offered in offered_header.split(","):
        name = offered.strip()
        if name in supported:
            return name
    return None

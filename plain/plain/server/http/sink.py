"""Request body ingestion: memory up to a threshold, disk spool beyond it.

The body sink is fed decoded body bytes on the event loop — h1 socket
reads and h2 DATA frames alike — and enforces the request-size policy on
bytes actually received, never on a declared Content-Length. When a body
outgrows the in-memory threshold it spills to an anonymous temp file
(``O_TMPFILE`` on Linux, unlinked immediately elsewhere), so a killed
worker can never leak spooled disk and the file never has a path an
attacker could reach.

``ChunkedDecoder`` is the push-mode companion for HTTP/1.1
``Transfer-Encoding: chunked``: raw wire bytes go in, decoded body bytes
come out, so the spool only ever holds clean body content and chunked
and declared-length bodies are indistinguishable downstream.
"""

from __future__ import annotations

import io
import tempfile
from typing import TYPE_CHECKING, cast

from .errors import BodyBudgetExceeded, ChunkedFramingError, LimitRequestBody

if TYPE_CHECKING:
    from plain.http.request import RequestStream

# Ceiling on the chunk-size line (hex size + optional extensions). A
# legitimate line is tens of bytes; without a cap, a client trickling
# bytes that never contain \r\n grows the decoder's buffer without bound
# on a single pre-auth request.
CHUNK_SIZE_LINE_MAX = 8192

# Trailer section cap — one header field's worth (LIMIT_REQUEST_FIELD_SIZE
# scale). Deliberately far tighter than the in-band header budget:
# legitimate trailers are a checksum or two, and this bounds what a
# hostile sender can make the decoder buffer after the last chunk.
MAX_TRAILER_SIZE = 8192

# Grace period (seconds) before SERVER_BODY_MIN_BYTES_PER_SECOND is
# enforced, so TCP slow-start and a briefly congested link don't get a
# request killed before it has a chance to ramp up.
BODY_RATE_GRACE_PERIOD = 5.0

# Once a client has met the rate floor across this much waiting, its
# counters reset (with a fresh grace period). Without the reset, every
# byte sent early banks 1/min_rate seconds of allowed future silence —
# a fast-start dripper could send 10MB at full speed and then drip one
# byte per recv-timeout for hours while holding all of it in the
# worker's in-flight budget.
BODY_RATE_WINDOW = 30.0

_HEX_DIGITS = frozenset(b"0123456789abcdefABCDEF")


class BodyBudget:
    """Worker-wide cap on in-flight request-body bytes (RAM + disk).

    Every sink charges the bytes it accepts here and releases them when
    it closes, so the worker's total body footprint stays bounded no
    matter how many connections upload at once. A request that would
    push past the limit is rejected with a 503 — load shedding, not
    queueing: making it wait instead could deadlock (in-flight uploads
    holding budget while waiting on each other to release it).

    All accounting happens on the event loop, so a plain counter is
    enough.
    """

    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.used = 0

    def charge(self, n: int) -> None:
        if self.limit is not None and self.used + n > self.limit:
            raise BodyBudgetExceeded(self.limit)
        self.used += n

    def release(self, n: int) -> None:
        self.used -= n


class BodyRateFloor:
    """Minimum-throughput floor over a request body's receipt.

    Enforces SERVER_BODY_MIN_BYTES_PER_SECOND against the time spent
    actively waiting for the client's bytes — never wall clock — so
    event-loop time spent decoding or spooling between recvs can't
    penalize the client. Per-recv inactivity timeouts can't stop a slow
    drip that sends one byte per interval; this can.

    The floor is windowed: it must be sustained across every
    BODY_RATE_WINDOW of waiting, not merely averaged over the body's
    lifetime, so holding in-flight budget always costs min_rate for as
    long as it's held. Callers record() each wait and its yield, then
    check violated() — only when more bytes are still expected, so a
    body whose final recv arrives late is served, never 408'd.
    """

    def __init__(self, min_rate: int) -> None:
        self.min_rate = min_rate
        self.waited: float = 0.0
        self.received: int = 0

    def record(self, *, waited: float, received: int) -> None:
        self.waited += waited
        self.received += received

    def violated(self) -> bool:
        if self.min_rate <= 0 or self.waited <= BODY_RATE_GRACE_PERIOD:
            return False
        # Charge only post-grace wait time, so a client isn't killed for
        # a slow start or one brief stall on a small body.
        if self.received < self.min_rate * (self.waited - BODY_RATE_GRACE_PERIOD):
            return True
        # Floor met across a full window — start a fresh one so early
        # bytes can't bank unbounded credit (see BODY_RATE_WINDOW).
        if self.waited >= BODY_RATE_WINDOW:
            self.waited = 0.0
            self.received = 0
        return False


class BodySink:
    """Collects one request body; memory-first, spooling past spool_size.

    feed() decoded bytes as they arrive; finish() seals the body and
    returns a file-like stream positioned at the start, suitable for
    ``request._stream`` (the multipart parser and ``request.body`` read
    it like any file). close() discards everything and releases the
    budget — safe to call at any point, including after finish().

    Raises LimitRequestBody past max_size (the per-request policy cap)
    and BodyBudgetExceeded past the worker-wide budget — cap first, so
    a single oversized body draws the specific 413, never a
    retry-inviting 503.
    """

    def __init__(
        self,
        *,
        spool_size: int,
        max_size: int | None,
        budget: BodyBudget | None = None,
    ) -> None:
        self.spool_size = spool_size
        self.max_size = max_size
        self.received = 0
        self._budget = budget
        # Allocated on the first feed — body-less requests (the common
        # case) never pay for a SpooledTemporaryFile.
        self._file: tempfile.SpooledTemporaryFile[bytes] | None = None
        self._finished = False

    @property
    def spooled(self) -> bool:
        """True once the body has spilled from memory to disk.

        SpooledTemporaryFile rolls over when a write takes it strictly
        past max_size, so this mirrors its state without reaching into
        its internals.
        """
        return self.received > self.spool_size

    def feed(self, data: bytes) -> None:
        assert not self._finished, "feed() after finish()"
        size = len(data)
        if self.max_size is not None and self.received + size > self.max_size:
            raise LimitRequestBody(self.received + size, self.max_size)
        if self._budget is not None:
            self._budget.charge(size)
        self.received += size
        if self._file is None:
            # Held for the request's lifetime, closed via close() — not
            # a context manager by design.
            self._file = tempfile.SpooledTemporaryFile(  # noqa: SIM115
                max_size=self.spool_size
            )
        self._file.write(data)

    def finish(self) -> RequestStream:
        """Seal the body and return the readable stream, rewound."""
        assert not self._finished, "finish() called twice"
        self._finished = True
        if self._file is None:
            return io.BytesIO()
        self._file.seek(0)
        # typeshed's SpooledTemporaryFile.read/readline stubs omit the
        # None-accepting overload that their runtime delegates (BytesIO,
        # BufferedRandom) support, so the protocol match needs a cast.
        return cast("RequestStream", self._file)

    def close(self) -> None:
        # Also seals against a stray feed() after teardown (the assert in
        # feed() only guards against feed-after-finish).
        self._finished = True
        if self._budget is not None:
            self._budget.release(self.received)
            self._budget = None
        if self._file is not None:
            self._file.close()
            self._file = None

    def detach(self) -> None:
        """Release the budget but leave the file for GC to close.

        For when the body may still be read by a thread that outlives
        this task — a cancelled dispatch keeps its executor thread
        running, and closing the file out from under a view mid-read
        would raise. The view holds its own reference (via finish()), so
        the anonymous temp file survives until that thread drops it and
        GC reclaims it.
        """
        self._finished = True
        if self._budget is not None:
            self._budget.release(self.received)
            self._budget = None
        self._file = None


class ChunkedDecoder:
    """Incremental Transfer-Encoding: chunked decoder (push mode).

    feed() raw wire bytes; each call returns the body bytes decoded from
    them. ``finished`` flips once the terminal chunk and any trailers
    have been consumed; after that ``trailers`` holds the raw trailer
    lines (b"" when none) and ``leftover`` holds any bytes past the
    terminator — the start of a pipelined request, for the caller to
    deal with. Raises ChunkedFramingError for malformed framing, an
    over-long chunk-size line, or an over-long trailer section.
    """

    def __init__(self) -> None:
        self.finished = False
        self.trailers = b""
        self.leftover = b""
        self._buf = bytearray()
        # State: "size" (reading a chunk-size line), "data" (inside a
        # chunk, _remaining bytes + trailing CRLF to go), "trailers".
        self._state = "size"
        self._remaining = 0

    def feed(self, data: bytes) -> bytes:
        assert not self.finished, "feed() after the terminal chunk"

        # Zero-copy fast path: mid-chunk with nothing buffered and the
        # whole feed inside the current chunk — the dominant case for
        # real encoders, whose chunks are far larger than one recv —
        # passes the bytes straight through untouched.
        if self._state == "data" and not self._buf and self._remaining >= len(data):
            self._remaining -= len(data)
            return data

        self._buf.extend(data)
        pieces: list[bytes] = []
        buf = self._buf
        # A cursor instead of deleting consumed prefixes per chunk keeps
        # one feed() O(len(data)) — repeated front-deletion would shift
        # the remainder once per chunk (quadratic on a buffer holding
        # many small chunks). Consumed bytes are dropped once, on exit.
        pos = 0

        try:
            while True:
                if self._state == "size":
                    crlf = buf.find(b"\r\n", pos)
                    if crlf < 0:
                        if len(buf) - pos > CHUNK_SIZE_LINE_MAX:
                            raise ChunkedFramingError("chunk size line too long")
                        return b"".join(pieces)
                    if crlf - pos > CHUNK_SIZE_LINE_MAX:
                        raise ChunkedFramingError("chunk size line too long")
                    size_line = bytes(memoryview(buf)[pos:crlf])
                    pos = crlf + 2
                    semi = size_line.find(b";")
                    if semi >= 0:
                        # RFC 9112 §7.1.1 permits BWS before the ";" of
                        # a chunk extension ("5 ;ext"), but only there —
                        # a bare "5 " with no extension stays rejected.
                        size_line = size_line[:semi].rstrip(b" \t")
                    # RFC 9112 §7.1 chunk-size is 1*HEXDIG — nothing else.
                    # int(_, 16) is a Python-literal parser that also
                    # accepts "0x", "+", "_", and (after strip) leading
                    # whitespace, any of which lets an upstream that
                    # parses hex strictly disagree with us about where
                    # the body ends — a request-smuggling primitive.
                    # Validate the token ourselves.
                    if not size_line or any(c not in _HEX_DIGITS for c in size_line):
                        raise ChunkedFramingError(f"bad chunk size {size_line[:32]!r}")
                    size = int(size_line, 16)
                    if size == 0:
                        self._state = "trailers"
                        continue
                    self._remaining = size
                    self._state = "data"

                elif self._state == "data":
                    if self._remaining > 0:
                        take = min(self._remaining, len(buf) - pos)
                        if take == 0:
                            return b"".join(pieces)
                        pieces.append(bytes(memoryview(buf)[pos : pos + take]))
                        pos += take
                        self._remaining -= take
                    # Chunk data is followed by CRLF.
                    if self._remaining == 0:
                        if len(buf) - pos < 2:
                            return b"".join(pieces)
                        if buf[pos : pos + 2] != b"\r\n":
                            raise ChunkedFramingError("missing CRLF after chunk data")
                        pos += 2
                        self._state = "size"

                elif self._state == "trailers":
                    # Either an immediate CRLF (no trailers) or trailer
                    # lines terminated by CRLFCRLF.
                    if buf[pos : pos + 2] == b"\r\n":
                        self._finish(trailers=b"", end=pos + 2)
                        return b"".join(pieces)
                    end = buf.find(b"\r\n\r\n", pos)
                    if end < 0:
                        if len(buf) - pos > MAX_TRAILER_SIZE:
                            raise ChunkedFramingError("trailer section too large")
                        return b"".join(pieces)
                    if end - pos > MAX_TRAILER_SIZE:
                        raise ChunkedFramingError("trailer section too large")
                    self._finish(trailers=bytes(buf[pos:end]), end=end + 4)
                    return b"".join(pieces)
        finally:
            if not self.finished and pos:
                del buf[:pos]

    def _finish(self, *, trailers: bytes, end: int) -> None:
        self.trailers = trailers
        self.leftover = bytes(self._buf[end:])
        self._buf.clear()
        self.finished = True

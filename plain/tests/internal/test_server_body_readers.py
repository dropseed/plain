"""The h1 body-reader pipeline: Unreader buffering, LengthReader, ChunkedReader.

These classes shuttle request bodies between the pre-buffered/bridged
byte source and the request parser. The buffer handling must be O(n) in
total body size: the pre-buffer path hands the ENTIRE body to a
BufferUnreader up front, and the original BytesIO implementation copied
the whole remaining buffer on every read — quadratic, which turned a
25MB upload into ~20s of CPU (issue #98). The canaries at the bottom pin
the linear behavior.
"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, cast

import pytest
from plain.http import BadRequestError400
from plain.server.http.body import Body, ChunkedReader, LengthReader
from plain.server.http.unreader import BufferUnreader, Unreader
from server_stubs import chunked_payload

if TYPE_CHECKING:
    from plain.server.http.message import Message


def _pattern(n: int, seed: int = 42) -> bytes:
    # Aperiodic deterministic data so offset/reassembly/reordering bugs
    # can't hide (uniform filler masks byte-rotation entirely).
    return random.Random(seed).randbytes(n)


class ScriptedUnreader(Unreader):
    """Unreader fed from a fixed list of chunks, counting chunk() calls."""

    def __init__(self, chunks: list[bytes]) -> None:
        super().__init__()
        self.remaining = list(chunks)
        self.chunk_calls = 0

    def chunk(self) -> bytes:
        self.chunk_calls += 1
        if self.remaining:
            return self.remaining.pop(0)
        return b""


class CountingBufferUnreader(BufferUnreader):
    """Tallies every byte handed out, to detect drain-and-unread churn."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.bytes_returned = 0

    def read(self, size: int | None = None) -> bytes:
        data = super().read(size)
        self.bytes_returned += len(data)
        return data

    def read_some(self, max_size: int) -> bytes:
        data = super().read_some(max_size)
        self.bytes_returned += len(data)
        return data


class StubTrailerReq:
    """Just enough Message for ChunkedReader's trailer handling."""

    max_buffer_headers = 32 * 1024

    def __init__(self) -> None:
        self.trailers: list[tuple[str, str]] | None = None

    def parse_headers(
        self, blob: bytes, from_trailer: bool = False
    ) -> list[tuple[str, str]]:
        # Minimal header-line split, enough to assert trailers landed.
        headers = []
        for line in blob.split(b"\r\n"):
            if b":" in line:
                name, _, value = line.partition(b":")
                headers.append((name.decode().upper(), value.strip().decode()))
        return headers


def _read_all(body: Body) -> bytes:
    out = []
    while piece := body.read(1024 * 1024):
        out.append(piece)
    return b"".join(out)


def _chunked_body(unreader: Unreader) -> Body:
    # ChunkedReader only touches req for trailer handling, which any
    # chunked payload can reach (the terminator landing on a read-window
    # boundary enters parse_trailers) — so always give it the stub
    # instead of building a fully parsed Message.
    return Body(ChunkedReader(cast("Message", StubTrailerReq()), unreader))


# ---------------------------------------------------------------------------
# Unreader semantics
# ---------------------------------------------------------------------------


def test_unsized_read_drains_buffer():
    unreader = BufferUnreader(b"hello world")
    assert unreader.read() == b"hello world"
    assert unreader.read() == b""


def test_sized_reads_reassemble_across_chunk_boundaries():
    data = _pattern(10_000)
    # Feed in awkward chunk sizes, read back in different awkward sizes.
    chunks = []
    pos = 0
    for size in (1, 7, 300, 4096, 5596):
        chunks.append(data[pos : pos + size])
        pos += size
    unreader = ScriptedUnreader(chunks)

    out = []
    for size in (3, 1, 1023, 5000, 8192):
        out.append(unreader.read(size))
    assert b"".join(out) == data
    assert unreader.read(1) == b""


def test_sized_read_returns_partial_at_eof():
    unreader = ScriptedUnreader([b"abc"])
    assert unreader.read(10) == b"abc"
    assert unreader.read(10) == b""


def test_read_zero_and_negative():
    unreader = BufferUnreader(b"abc")
    assert unreader.read(0) == b""
    # Negative size means "everything", like the original implementation.
    assert unreader.read(-1) == b"abc"


def test_unread_is_returned_first():
    # unread() pushes to the FRONT — even when data is still buffered,
    # and even when the front chunk is partially consumed.
    unreader = BufferUnreader(b"abcdef")
    assert unreader.read(2) == b"ab"
    unreader.unread(b"ab")
    assert unreader.read() == b"abcdef"


def test_read_some_returns_available_without_waiting():
    unreader = ScriptedUnreader([b"0123456789", b"more"])
    # Only one chunk() call — read_some never blocks accumulating max_size.
    assert unreader.read_some(1000) == b"0123456789"
    assert unreader.chunk_calls == 1


def test_read_some_caps_at_max_size():
    data = _pattern(100_000)
    unreader = BufferUnreader(data)
    first = unreader.read_some(65536)
    assert first == data[:65536]
    assert unreader.read_some(65536) == data[65536:]
    assert unreader.read_some(65536) == b""


def test_read_some_rejects_non_positive_max_size():
    unreader = BufferUnreader(b"abc")
    with pytest.raises(ValueError, match="max_size"):
        unreader.read_some(0)


# ---------------------------------------------------------------------------
# LengthReader
# ---------------------------------------------------------------------------


def test_length_reader_delivers_exact_length_and_leaves_pipelined_bytes():
    body = _pattern(50_000)
    unreader = BufferUnreader(body + b"GET /next HTTP/1.1\r\n")
    reader = LengthReader(unreader, len(body))

    out = []
    while piece := reader.read(1024):
        out.append(piece)
    assert b"".join(out) == body
    # Bytes past the declared length stay in the unreader for the caller.
    assert unreader.read() == b"GET /next HTTP/1.1\r\n"


def test_length_reader_truncated_body_finishes():
    unreader = BufferUnreader(b"abc")
    reader = LengthReader(unreader, 10)
    # Short reads are normal (streaming) — only b"" means EOF, at which
    # point length must reach 0 so the reader registers as finished.
    assert reader.read(10) == b"abc"
    assert reader.read(10) == b""
    assert reader.length == 0
    assert reader.read(10) == b""


def test_length_reader_returns_arrived_bytes_without_waiting():
    # A streaming body must hand back what has arrived instead of
    # blocking until a full stride accumulates — readline() on a short
    # line the client already sent must not stall (issue: for-line-in-
    # request over a bridged body timed out waiting for 1024 bytes).
    unreader = ScriptedUnreader([b"hi\n", b"rest"])
    reader = LengthReader(unreader, 10_000)
    assert reader.read(1024) == b"hi\n"
    assert unreader.chunk_calls == 1


def test_body_readline_returns_short_line_promptly():
    unreader = ScriptedUnreader([b"hi\n", b"never-read"])
    body = Body(LengthReader(unreader, 10_000))
    assert body.readline() == b"hi\n"
    assert unreader.chunk_calls == 1


# ---------------------------------------------------------------------------
# ChunkedReader (via Body, as the parser wires it)
# ---------------------------------------------------------------------------


def test_chunked_roundtrip_with_odd_chunk_sizes():
    data = _pattern(100_000)
    for chunk_size in (1, 13, 1024, 65536, 200_000):
        body = _chunked_body(BufferUnreader(chunked_payload(data, chunk_size)))
        assert _read_all(body) == data


def test_chunked_leaves_pipelined_bytes_in_unreader():
    # Body and trailing bytes both exceed the parser's 64KB read cap, so
    # the unreader is NOT fully drained when parse_trailers unread()s the
    # over-read tail — this catches unread() reordering the stream
    # (aperiodic data on both sides; uniform filler would mask rotation).
    data = _pattern(200_000)
    pipelined = _pattern(100_000, seed=9)
    unreader = BufferUnreader(chunked_payload(data, 200_000) + pipelined)
    body = _chunked_body(unreader)
    assert _read_all(body) == data
    assert unreader.read() == pipelined


def test_chunk_size_line_flood_is_rejected():
    # A stream that never terminates its chunk-size line must error out
    # instead of buffering and re-scanning it without bound. The error is
    # an HTTPException (400) because it fires during lazy body reads
    # mid-dispatch, where a ParseException would be misread as an OSError
    # and produce no response at all.
    body = _chunked_body(BufferUnreader(b"f" * 100_000))
    with pytest.raises(BadRequestError400):
        body.read(1024)


def test_overlong_chunk_size_line_rejected_even_when_terminated():
    # The whole overlong line (with its CRLF) can arrive in a single
    # read, skipping the accumulation loop's cap — the post-loop check
    # must still reject it.
    payload = b"0;ext=" + b"x" * 9000 + b"\r\n\r\n"
    body = _chunked_body(BufferUnreader(payload))
    with pytest.raises(BadRequestError400):
        body.read(1024)


def test_trailer_flood_is_rejected():
    # Same for trailers: bounded by the request's max_buffer_headers.
    payload = chunked_payload(b"data", 4, trailer=b"X-Junk: " + b"j" * 100_000)
    body = _chunked_body(BufferUnreader(payload))
    with pytest.raises(BadRequestError400):
        body.read(1024)


def test_chunked_trailers_parse_and_preserve_pipelined_tail():
    # A well-formed trailer section is consumed exactly: trailers land on
    # the request and bytes past the terminator stay in the unreader.
    data = _pattern(10_000)
    tail = b"GET /next HTTP/1.1\r\n"
    payload = chunked_payload(data, 1024, trailer=b"X-Trailer: yes")
    req = StubTrailerReq()
    unreader = BufferUnreader(payload + tail)
    body = Body(ChunkedReader(cast("Message", req), unreader))
    assert _read_all(body) == data
    assert req.trailers == [("X-TRAILER", "yes")]
    assert unreader.read() == tail


def test_chunked_terminator_on_read_window_boundary():
    # The terminating 0-chunk landing at the edge of a 64KB read window
    # sends the parser into parse_trailers with an empty buffer — it must
    # keep reading to the blank line, not error. (Regression guard: the
    # trailer path is reachable by ordinary chunk alignment, so
    # ChunkedReader always needs a real req, and the cap check must not
    # fire on an empty buffer.)
    payload = b"fff5\r\n" + b"x" * 0xFFF5 + b"\r\n" + b"0\r\n\r\n"
    body = _chunked_body(BufferUnreader(payload))
    assert _read_all(body) == b"x" * 0xFFF5


# ---------------------------------------------------------------------------
# O(n) canaries
# ---------------------------------------------------------------------------


def test_length_body_bytes_returned_once():
    # The historical quadratic (issue #98) drained the whole buffer and
    # unread the remainder on every read, so total bytes handed out grew
    # as n^2/stride. Deterministic and machine-independent.
    n = 4 * 1024 * 1024
    unreader = CountingBufferUnreader(b"x" * n)
    body = Body(LengthReader(unreader, n))
    assert len(_read_all(body)) == n
    assert unreader.bytes_returned <= 2 * n


def test_chunked_body_bytes_returned_once():
    n = 4 * 1024 * 1024
    unreader = CountingBufferUnreader(chunked_payload(b"x" * n, 16 * 1024))
    body = _chunked_body(unreader)
    assert len(_read_all(body)) == n
    assert unreader.bytes_returned <= 2 * n


def test_small_read_does_not_wait_for_unrequested_bytes():
    # request.read(1) on a streaming body must not block accumulating a
    # larger internal stride — only what the caller asked for.
    unreader = ScriptedUnreader([b"a", b"b", b"c"])
    body = Body(LengthReader(unreader, 3))
    assert body.read(1) == b"a"
    assert unreader.chunk_calls == 1


def test_large_prebuffered_length_body_reads_in_linear_time():
    # Quadratic buffer handling took ~23s here; linear is ~15ms. The
    # bound is ~100x the linear time so slow CI never flakes, while a
    # quadratic regression overshoots it by an order of magnitude.
    n = 25 * 1024 * 1024
    body = Body(LengthReader(BufferUnreader(b"x" * n), n))
    start = time.perf_counter()
    got = len(_read_all(body))
    elapsed = time.perf_counter() - start
    assert got == n
    assert elapsed < 2.0, f"25MB body took {elapsed:.2f}s — quadratic regression?"


def test_large_prebuffered_chunked_body_reads_in_linear_time():
    # Catches quadratic slicing inside the chunk parser (bytes-returned
    # accounting can't see internal copies). Framed by repeating one
    # 16KB piece so peak memory stays ~one copy of the payload.
    piece = b"4000\r\n" + b"x" * 0x4000 + b"\r\n"
    count = 3072  # 48MB of body
    n = 0x4000 * count
    unreader = BufferUnreader(piece * count + b"0\r\n\r\n")
    body = _chunked_body(unreader)
    start = time.perf_counter()
    got = len(_read_all(body))
    elapsed = time.perf_counter() - start
    assert got == n
    assert elapsed < 2.0, (
        f"48MB chunked body took {elapsed:.2f}s — quadratic regression?"
    )

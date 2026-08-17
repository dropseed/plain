"""Unit contract for BodySink and ChunkedDecoder (pre-wiring).

These are the building blocks of the unified body-ingestion path: the
sink holds a request body (memory first, disk spool past the threshold)
and enforces the policy cap on received bytes; the decoder turns raw
chunked wire bytes into clean body bytes incrementally on the event
loop. Both are exercised here in isolation, byte-split-adversarially,
before any protocol wiring depends on them.
"""

from __future__ import annotations

import pytest
from plain.server.http.errors import ChunkedFramingError, LimitRequestBody
from plain.server.http.sink import (
    MAX_TRAILER_SIZE,
    BodySink,
    ChunkedDecoder,
)

# ---------------------------------------------------------------------------
# BodySink
# ---------------------------------------------------------------------------


def _pattern(n: int) -> bytes:
    # Aperiodic data so reordering or duplication can't cancel out.
    return bytes((i * 7 + i // 251) % 256 for i in range(n))


def test_sink_small_body_stays_in_memory():
    sink = BodySink(spool_size=1024, max_size=None)
    sink.feed(b"hello ")
    sink.feed(b"world")
    assert not sink.spooled
    stream = sink.finish()
    assert stream.read() == b"hello world"
    assert sink.received == 11


def test_sink_spills_to_disk_past_threshold():
    sink = BodySink(spool_size=1024, max_size=None)
    data = _pattern(10_000)
    for i in range(0, len(data), 333):
        sink.feed(data[i : i + 333])
    assert sink.spooled
    stream = sink.finish()
    assert stream.read() == data


def test_sink_exactly_at_threshold_stays_in_memory():
    sink = BodySink(spool_size=1024, max_size=None)
    sink.feed(b"x" * 1024)
    assert not sink.spooled


def test_sink_cap_allows_exactly_max_size():
    sink = BodySink(spool_size=64, max_size=100)
    sink.feed(b"x" * 100)
    assert sink.finish().read() == b"x" * 100


def test_sink_cap_raises_on_the_violating_feed():
    sink = BodySink(spool_size=64, max_size=100)
    sink.feed(b"x" * 100)
    with pytest.raises(LimitRequestBody):
        sink.feed(b"x")


def test_sink_cap_counts_received_bytes_not_declared_length():
    # The cap must bind on what actually arrives — a lying Content-Length
    # can't bypass it because the sink never consults one.
    sink = BodySink(spool_size=64, max_size=100)
    with pytest.raises(LimitRequestBody):
        sink.feed(b"x" * 101)


def test_sink_unlimited_when_max_size_is_none():
    sink = BodySink(spool_size=64, max_size=None)
    sink.feed(b"x" * 100_000)
    assert sink.received == 100_000


def test_sink_stream_supports_readline():
    sink = BodySink(spool_size=8, max_size=None)
    sink.feed(b"line one\nline two\n")  # spooled: readline crosses the disk path
    stream = sink.finish()
    assert stream.readline() == b"line one\n"
    assert stream.readline() == b"line two\n"
    assert stream.readline() == b""


def test_sink_close_releases_the_stream():
    sink = BodySink(spool_size=8, max_size=None)
    sink.feed(b"x" * 100)
    stream = sink.finish()
    sink.close()
    with pytest.raises(ValueError, match="closed file"):
        stream.read()


def test_sink_close_before_finish_discards():
    sink = BodySink(spool_size=8, max_size=None)
    sink.feed(b"x" * 100)
    sink.close()  # no error, nothing leaked


def test_sink_never_fed_allocates_no_file():
    # Body-less requests must not pay for a SpooledTemporaryFile.
    sink = BodySink(spool_size=8, max_size=None)
    assert sink._file is None
    assert sink.finish().read() == b""


def test_sink_feed_after_close_is_blocked():
    # close() seals the sink so a stray feed can't allocate an orphan
    # file or bypass the budget.
    sink = BodySink(spool_size=8, max_size=None)
    sink.close()
    with pytest.raises(AssertionError):
        sink.feed(b"x")


def test_sink_detach_keeps_the_stream_readable():
    # detach() releases the budget but leaves the file open for a reader
    # (a cancelled dispatch's executor thread) that outlives the sink.
    from plain.server.http.sink import BodyBudget

    budget = BodyBudget(1000)
    sink = BodySink(spool_size=4, max_size=None, budget=budget)
    sink.feed(b"hello world")  # spooled
    stream = sink.finish()
    sink.detach()
    assert budget.used == 0  # budget released
    assert stream.read() == b"hello world"  # file still open


# ---------------------------------------------------------------------------
# ChunkedDecoder
# ---------------------------------------------------------------------------


def _encode_chunked(payload: bytes, chunk_size: int, trailers: bytes = b"") -> bytes:
    out = bytearray()
    for i in range(0, len(payload), chunk_size):
        chunk = payload[i : i + chunk_size]
        out += f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n"
    out += b"0\r\n"
    if trailers:
        out += trailers + b"\r\n"
    out += b"\r\n"
    return bytes(out)


def _decode_all(wire: bytes, *, split: int) -> tuple[bytes, ChunkedDecoder]:
    decoder = ChunkedDecoder()
    decoded = bytearray()
    for i in range(0, len(wire), split):
        if decoder.finished:
            break
        decoded += decoder.feed(wire[i : i + split])
    return bytes(decoded), decoder


@pytest.mark.parametrize("split", [1, 2, 3, 7, 64, 10_000])
def test_decoder_round_trips_across_any_feed_split(split: int):
    payload = _pattern(5000)
    wire = _encode_chunked(payload, 613)
    decoded, decoder = _decode_all(wire, split=split)
    assert decoded == payload
    assert decoder.finished
    assert decoder.trailers == b""
    assert decoder.leftover == b""


@pytest.mark.parametrize("split", [1, 5, 10_000])
def test_decoder_captures_trailers(split: int):
    payload = _pattern(300)
    wire = _encode_chunked(payload, 100, trailers=b"X-Checksum: abc")
    decoded, decoder = _decode_all(wire, split=split)
    assert decoded == payload
    assert decoder.finished
    assert decoder.trailers == b"X-Checksum: abc"


def test_decoder_multi_line_trailers():
    wire = b"3\r\nabc\r\n0\r\nA: 1\r\nB: 2\r\n\r\n"
    decoded, decoder = _decode_all(wire, split=len(wire))
    assert decoded == b"abc"
    assert decoder.trailers == b"A: 1\r\nB: 2"


def test_decoder_reports_pipelined_leftover():
    wire = _encode_chunked(b"abc", 3) + b"GET /next HTTP/1.1\r\n"
    decoded, decoder = _decode_all(wire, split=len(wire))
    assert decoded == b"abc"
    assert decoder.finished
    assert decoder.leftover == b"GET /next HTTP/1.1\r\n"


def test_decoder_allows_bws_before_chunk_extension():
    # RFC 9112 §7.1.1 permits BWS before the ";" of a chunk extension
    # ("5 ;ext") — but only there; a bare trailing space with no
    # extension stays rejected (see the strict HEXDIG cases below).
    decoder = ChunkedDecoder()
    body = decoder.feed(b"5 \t;name=value\r\nhello\r\n0\r\n\r\n")
    assert body == b"hello"
    assert decoder.finished


def test_decoder_chunk_extensions_are_ignored():
    wire = b"3;ext=value\r\nabc\r\n0\r\n\r\n"
    decoded, decoder = _decode_all(wire, split=len(wire))
    assert decoded == b"abc"
    assert decoder.finished


def test_decoder_empty_body():
    decoded, decoder = _decode_all(b"0\r\n\r\n", split=1)
    assert decoded == b""
    assert decoder.finished


def test_decoder_binary_payload_with_crlf_and_fake_terminators():
    # Chunk data containing CRLFs, hex-like lines, and "0\r\n\r\n" must
    # never confuse the framing — sizes are authoritative.
    payload = b"\r\n0\r\n\r\n" * 100 + _pattern(500)
    wire = _encode_chunked(payload, 37)
    decoded, decoder = _decode_all(wire, split=3)
    assert decoded == payload
    assert decoder.finished


def test_decoder_invalid_chunk_size_raises():
    decoder = ChunkedDecoder()
    with pytest.raises(ChunkedFramingError):
        decoder.feed(b"zzz\r\nabc\r\n0\r\n\r\n")


def test_decoder_negative_chunk_size_raises():
    decoder = ChunkedDecoder()
    with pytest.raises(ChunkedFramingError):
        decoder.feed(b"-5\r\nabc\r\n0\r\n\r\n")


@pytest.mark.parametrize(
    "size_line",
    [
        b"0x5",  # Python literal prefix
        b"1_0",  # PEP 515 underscore
        b"+5",  # signed
        b" 5",  # leading space (bytes.strip would have eaten it)
        b"\x0b0",  # vertical tab prefix (bytes.strip too)
        b"",  # empty
        b"5 ",  # trailing space
    ],
)
def test_decoder_rejects_non_hexdigit_chunk_size(size_line: bytes):
    # RFC 9112 chunk-size is 1*HEXDIG. int(_, 16) is more permissive, and
    # any tolerance here is a smuggling primitive vs a strict upstream.
    decoder = ChunkedDecoder()
    with pytest.raises(ChunkedFramingError):
        decoder.feed(size_line + b"\r\nxxxxx\r\n0\r\n\r\n")


def test_decoder_missing_crlf_after_chunk_data_raises():
    decoder = ChunkedDecoder()
    with pytest.raises(ChunkedFramingError):
        decoder.feed(b"3\r\nabcXX0\r\n\r\n")


def test_decoder_over_long_chunk_size_line_raises():
    decoder = ChunkedDecoder()
    with pytest.raises(ChunkedFramingError):
        decoder.feed(b"3;" + b"x" * 9000)


def test_decoder_over_long_chunk_size_line_raises_even_when_terminated():
    # The cap must hold when the whole over-long line arrives in one feed
    # with its CRLF present — not just when it dribbles in.
    decoder = ChunkedDecoder()
    with pytest.raises(ChunkedFramingError):
        decoder.feed(b"3;" + b"x" * 9000 + b"\r\nabc\r\n0\r\n\r\n")


def test_decoder_trailer_flood_raises():
    decoder = ChunkedDecoder()
    decoder.feed(b"3\r\nabc\r\n0\r\n")
    with pytest.raises(ChunkedFramingError):
        decoder.feed(b"X: " + b"y" * (MAX_TRAILER_SIZE + 100))


def test_decoder_trailer_flood_raises_even_when_terminated():
    decoder = ChunkedDecoder()
    decoder.feed(b"3\r\nabc\r\n0\r\n")
    with pytest.raises(ChunkedFramingError):
        decoder.feed(b"X: " + b"y" * (MAX_TRAILER_SIZE + 100) + b"\r\n\r\n")


def test_decoder_many_small_chunks_in_one_feed_is_linear_time():
    # A single feed holding thousands of small chunks must decode in one
    # pass — per-chunk front-deletion of the buffer would shift the
    # remainder once per chunk (quadratic; seconds at this size). The
    # bound is ~100x the linear time so slow CI never flakes, while a
    # quadratic regression overshoots it by an order of magnitude.
    import time

    piece = b"4000\r\n" + b"x" * 0x4000 + b"\r\n"
    count = 3072  # 48MB of body
    wire = piece * count + b"0\r\n\r\n"
    decoder = ChunkedDecoder()
    start = time.perf_counter()
    decoded = decoder.feed(wire)
    elapsed = time.perf_counter() - start
    assert decoder.finished
    assert len(decoded) == 0x4000 * count
    assert elapsed < 2.0, f"48MB chunked feed took {elapsed:.2f}s — quadratic?"


# ---------------------------------------------------------------------------
# Composition: decoder feeding sink (the h1 chunked ingest shape)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("split", [1, 13, 4096])
def test_chunked_ingest_through_sink_round_trips(split: int):
    payload = _pattern(50_000)
    wire = _encode_chunked(payload, 1000)
    sink = BodySink(spool_size=4096, max_size=None)
    decoder = ChunkedDecoder()
    for i in range(0, len(wire), split):
        if decoder.finished:
            break
        sink.feed(decoder.feed(wire[i : i + split]))
    assert decoder.finished
    assert sink.spooled
    assert sink.finish().read() == payload


def test_chunked_ingest_enforces_cap_on_decoded_bytes():
    payload = b"x" * 5000
    wire = _encode_chunked(payload, 500)
    sink = BodySink(spool_size=64, max_size=1000)
    decoder = ChunkedDecoder()

    def ingest() -> None:
        for i in range(0, len(wire), 100):
            sink.feed(decoder.feed(wire[i : i + 100]))

    with pytest.raises(LimitRequestBody):
        ingest()

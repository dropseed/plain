"""Change detectors for the RFC 6455 frame codec.

`plain.http.websocket_frames` is a private module — nothing here is exported
from `plain.http`, and a user never calls `read_frame` or `encode_frame`
directly. The contract these pin belongs to the wire, not to the Python API:
the byte layout of a frame, what counts as a protocol violation, and the
reader's promise that it survives a `recv` that hands back one byte at a time.
"""

import asyncio
import struct

from plain.http.websocket import select_subprotocol
from plain.http.websocket_frames import (
    CLOSE_NO_STATUS,
    CLOSE_NORMAL,
    MAX_CONTROL_PAYLOAD,
    OP_BINARY,
    OP_CLOSE,
    OP_CONTINUATION,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    Frame,
    IncompleteFrame,
    PayloadTooLarge,
    ProtocolError,
    apply_mask,
    compute_accept_key,
    encode_close,
    encode_frame,
    is_valid_close_code,
    parse_close_payload,
    read_frame,
)
from plain.testing import cases, raises

MAX_PAYLOAD = 1024 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_masked_frame(
    opcode: int,
    payload: bytes,
    fin: bool = True,
    mask: bytes = b"\x01\x02\x03\x04",
    force_64bit_length: bool = False,
) -> bytes:
    """Build a client-to-server masked frame.

    `force_64bit_length` uses the 8-byte length encoding regardless of size.
    """
    header = bytearray()
    header.append((0x80 if fin else 0x00) | (opcode & 0x0F))

    length = len(payload)
    if force_64bit_length or length >= 65536:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    elif length >= 126:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | length)

    header.extend(mask)
    return bytes(header) + apply_mask(payload, mask)


class _Recv:
    """An async `recv(n)` over a fixed byte string.

    Returns at most `chunk` bytes per call when one is given, so a reader that
    assumes `recv` fills its request falls over. `handed_out` is how many bytes
    the reader actually pulled, which is what proves an oversize frame was
    rejected from its header.
    """

    def __init__(self, data: bytes, chunk: int | None = None) -> None:
        self._data = data
        self._chunk = chunk
        self.handed_out = 0

    async def __call__(self, n: int) -> bytes:
        take = n if self._chunk is None else min(n, self._chunk)
        out = self._data[self.handed_out : self.handed_out + take]
        self.handed_out += len(out)
        return out


def _read_one(data: bytes, max_payload: int = MAX_PAYLOAD) -> Frame:
    return asyncio.run(read_frame(_Recv(data), max_payload))


# ---------------------------------------------------------------------------
# Frame encoding
# ---------------------------------------------------------------------------


def test_encode_text_frame():
    frame = encode_frame(OP_TEXT, b"hello")
    assert frame[0] == 0x81  # FIN + TEXT
    assert frame[1] == 5
    assert frame[2:] == b"hello"


def test_encode_binary_frame():
    frame = encode_frame(OP_BINARY, b"\x00\x01\x02")
    assert frame[0] == 0x82  # FIN + BINARY
    assert frame[1] == 3


def test_encode_empty_frame():
    frame = encode_frame(OP_TEXT, b"")
    assert frame[0] == 0x81
    assert frame[1] == 0


def test_encode_medium_payload():
    """A payload of 126-65535 bytes uses the 2-byte extended length."""
    payload = b"x" * 200
    frame = encode_frame(OP_TEXT, payload)
    assert frame[1] == 126
    assert struct.unpack("!H", frame[2:4])[0] == 200
    assert frame[4:] == payload


def test_encode_large_payload():
    """A payload over 65535 bytes uses the 8-byte extended length."""
    payload = b"x" * 70000
    frame = encode_frame(OP_TEXT, payload)
    assert frame[1] == 127
    assert struct.unpack("!Q", frame[2:10])[0] == 70000


def test_encode_no_fin():
    frame = encode_frame(OP_TEXT, b"partial", fin=False)
    assert frame[0] == 0x01  # no FIN + TEXT


def test_encode_never_masks():
    """Server frames are unmasked, so the high bit of byte 2 stays clear."""
    frame = encode_frame(OP_TEXT, b"hello")
    assert frame[1] & 0x80 == 0


def test_encode_ping():
    frame = encode_frame(OP_PING, b"")
    assert frame[0] == 0x89  # FIN + PING


def test_encode_pong():
    frame = encode_frame(OP_PONG, b"data")
    assert frame[0] == 0x8A  # FIN + PONG


def test_encode_close():
    frame = encode_close(CLOSE_NORMAL, "bye")
    assert frame[0] == 0x88  # FIN + CLOSE
    payload = frame[2:]
    assert struct.unpack("!H", payload[:2])[0] == 1000
    assert payload[2:] == b"bye"


def test_encode_close_defaults_to_normal():
    assert encode_close() == encode_frame(OP_CLOSE, struct.pack("!H", 1000))


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


def test_apply_mask_known_vector():
    """The worked example from RFC 6455 Section 5.7."""
    assert apply_mask(b"Hello", b"\x37\xfa\x21\x3d") == b"\x7f\x9f\x4d\x51\x58"


def test_apply_mask_empty():
    assert apply_mask(b"", b"\x01\x02\x03\x04") == b""


def test_apply_mask_exactly_8_bytes():
    mask = b"\x12\x34\x56\x78"
    assert apply_mask(apply_mask(b"12345678", mask), mask) == b"12345678"


@cases(1, 7, 8, 9, 15, 16, 17, 2000)
def test_apply_mask_roundtrip_across_the_chunk_boundary(size):
    """The repeated mask must line up for every payload length, including the `n % 4` tail."""
    mask = b"\xde\xad\xbe\xef"
    data = bytes(range(256)) * 16
    data = data[:size]
    masked = apply_mask(data, mask)
    assert len(masked) == size
    assert apply_mask(masked, mask) == data
    assert masked == bytes(b ^ mask[i % 4] for i, b in enumerate(data))


def test_apply_mask_invalid_mask_length():
    with raises(ValueError, match="4 bytes"):
        apply_mask(b"data", b"\x01\x02\x03")


# ---------------------------------------------------------------------------
# Close payloads
# ---------------------------------------------------------------------------


def test_close_payload_normal_close():
    result = parse_close_payload(struct.pack("!H", 1000) + b"goodbye")
    assert result.code == 1000
    assert result.reason == "goodbye"


def test_close_payload_code_only():
    result = parse_close_payload(struct.pack("!H", 1001))
    assert result.code == 1001
    assert result.reason == ""


def test_close_payload_empty_payload():
    """No payload means no status, which is 1005 and never sent back."""
    result = parse_close_payload(b"")
    assert result.code == CLOSE_NO_STATUS
    assert result.reason == ""


def test_close_payload_single_byte():
    with raises(ProtocolError, match="at least 2 bytes"):
        parse_close_payload(b"\x00")


@cases(0, 999, 1004, 1005, 1006, 1015, 2999, 5000)
def test_close_payload_reserved_and_out_of_range_codes(code):
    with raises(ProtocolError, match="Invalid close code"):
        parse_close_payload(struct.pack("!H", code))


@cases(1000, 1003, 1007, 1014, 3000, 3999, 4000, 4999)
def test_close_payload_accepted_codes(code):
    assert parse_close_payload(struct.pack("!H", code)).code == code


def test_close_payload_invalid_utf8_reason():
    with raises(ProtocolError, match="Invalid UTF-8"):
        parse_close_payload(struct.pack("!H", 1000) + b"\xff\xfe")


def test_close_payload_is_valid_close_code_table():
    assert is_valid_close_code(1000)
    assert not is_valid_close_code(1004)
    assert not is_valid_close_code(1005)
    assert not is_valid_close_code(1006)
    assert is_valid_close_code(1007)
    assert not is_valid_close_code(1015)
    assert is_valid_close_code(3000)
    assert is_valid_close_code(4999)


# ---------------------------------------------------------------------------
# Handshake key
# ---------------------------------------------------------------------------


def test_compute_accept_key_rfc_example():
    """The worked example from RFC 6455 Section 1.3."""
    assert compute_accept_key("dGhlIHNhbXBsZSBub25jZQ==") == (
        "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
    )


def test_compute_accept_key_different_keys_differ():
    assert compute_accept_key("x3JJHMbDL1EzLkh9GBhXDw==") != compute_accept_key(
        "dGhlIHNhbXBsZSBub25jZQ=="
    )


# ---------------------------------------------------------------------------
# Subprotocol selection
# ---------------------------------------------------------------------------


def test_select_subprotocol_no_header():
    assert select_subprotocol(None, ("binary",)) is None


def test_select_subprotocol_empty_header():
    assert select_subprotocol("", ("binary",)) is None


def test_select_subprotocol_nothing_supported():
    assert select_subprotocol("binary", ()) is None


def test_select_subprotocol_single_match():
    assert select_subprotocol("binary", ("binary",)) == "binary"


def test_select_subprotocol_no_overlap():
    assert select_subprotocol("chat, superchat", ("binary",)) is None


def test_select_subprotocol_first_client_offer_wins():
    """The client's order is the preference order, not ours."""
    assert select_subprotocol("chat,binary", ("binary", "chat")) == "chat"


def test_select_subprotocol_whitespace_around_commas():
    assert select_subprotocol("  chat ,  binary  ", ("binary",)) == "binary"


def test_select_subprotocol_case_sensitive():
    assert select_subprotocol("Binary", ("binary",)) is None
    assert select_subprotocol("binary", ("Binary",)) is None


# ---------------------------------------------------------------------------
# Reading frames
# ---------------------------------------------------------------------------


def test_read_text_frame():
    frame = _read_one(_make_masked_frame(OP_TEXT, b"hello"))
    assert frame.fin is True
    assert frame.opcode == OP_TEXT
    assert frame.payload == b"hello"


def test_read_binary_frame():
    frame = _read_one(_make_masked_frame(OP_BINARY, b"\x00\x01\x02"))
    assert frame.opcode == OP_BINARY
    assert frame.payload == b"\x00\x01\x02"


def test_read_empty_payload():
    frame = _read_one(_make_masked_frame(OP_TEXT, b""))
    assert frame.payload == b""


def test_read_ping_frame():
    frame = _read_one(_make_masked_frame(OP_PING, b""))
    assert frame.opcode == OP_PING


def test_read_close_frame():
    data = _make_masked_frame(OP_CLOSE, struct.pack("!H", 1000) + b"bye")
    frame = _read_one(data)
    assert frame.opcode == OP_CLOSE
    close = parse_close_payload(frame.payload)
    assert close.code == 1000
    assert close.reason == "bye"


def test_read_medium_payload():
    payload = b"x" * 200
    frame = _read_one(_make_masked_frame(OP_BINARY, payload))
    assert frame.payload == payload


def test_read_64_bit_length():
    payload = b"z" * 300
    frame = _read_one(_make_masked_frame(OP_BINARY, payload, force_64bit_length=True))
    assert frame.payload == payload


def test_read_frame_fragmented_text():
    data = _make_masked_frame(OP_TEXT, b"hel", fin=False) + _make_masked_frame(
        OP_CONTINUATION, b"lo"
    )

    async def run():
        recv = _Recv(data)
        return await read_frame(recv, MAX_PAYLOAD), await read_frame(recv, MAX_PAYLOAD)

    first, second = asyncio.run(run())
    assert first == Frame(fin=False, opcode=OP_TEXT, payload=b"hel")
    assert second == Frame(fin=True, opcode=OP_CONTINUATION, payload=b"lo")


def test_read_frame_reject_unmasked_frame():
    with raises(ProtocolError, match="not masked"):
        _read_one(bytes([0x81, 0x05]) + b"hello")


@cases(0xC1, 0xA1, 0x91)
def test_read_frame_reject_rsv_bits(first_byte):
    """RSV1 too — no extension is ever negotiated."""
    with raises(ProtocolError, match="RSV"):
        _read_one(bytes([first_byte, 0x80, 0x01, 0x02, 0x03, 0x04]))


def test_read_frame_reject_unknown_opcode():
    with raises(ProtocolError, match="Unknown opcode"):
        _read_one(bytes([0x85, 0x80, 0x01, 0x02, 0x03, 0x04]))


def test_read_frame_reject_fragmented_control_frame():
    with raises(ProtocolError, match="Fragmented control"):
        _read_one(_make_masked_frame(OP_PING, b"", fin=False))


def test_read_frame_reject_oversized_control_frame():
    data = _make_masked_frame(OP_PING, b"x" * (MAX_CONTROL_PAYLOAD + 1))
    with raises(ProtocolError, match="Control frame payload too long"):
        _read_one(data)


def test_read_frame_reject_64_bit_length_with_high_bit_set():
    header = bytes([0x82, 0xFF]) + struct.pack("!Q", 1 << 63)
    with raises(ProtocolError, match="high bit"):
        _read_one(header)


def test_read_frame_payload_over_max_is_rejected():
    data = _make_masked_frame(OP_BINARY, b"x" * 200)
    with raises(PayloadTooLarge) as caught:
        _read_one(data, max_payload=100)
    assert caught.exception.length == 200
    assert caught.exception.max_payload == 100


def test_read_frame_payload_too_large_is_a_protocol_error():
    # A size cap is policy, not a protocol violation: 1009, never 1002.
    assert not issubclass(PayloadTooLarge, ProtocolError)


def test_read_frame_huge_declared_length_never_reads_the_payload():
    """A frame claiming 4 GiB costs us ten bytes, not 4 GiB."""
    header = bytes([0x82, 0xFF]) + struct.pack("!Q", 4 * 1024**3)
    recv = _Recv(header + b"\x01\x02\x03\x04")

    with raises(PayloadTooLarge) as caught:
        asyncio.run(read_frame(recv, 1024))

    assert caught.exception.length == 4 * 1024**3
    # Two header bytes plus the eight length bytes — the mask and payload
    # were never asked for.
    assert recv.handed_out == 10


def test_read_frame_eof_at_frame_boundary():
    with raises(IncompleteFrame):
        _read_one(b"")


def test_read_frame_eof_mid_header():
    with raises(IncompleteFrame):
        _read_one(_make_masked_frame(OP_TEXT, b"hello")[:4])


def test_read_frame_eof_mid_payload():
    with raises(IncompleteFrame):
        _read_one(_make_masked_frame(OP_TEXT, b"hello")[:-2])


def test_read_frame_eof_mid_extended_length():
    with raises(IncompleteFrame):
        _read_one(bytes([0x82, 0xFF, 0x00, 0x00]))


# ---------------------------------------------------------------------------
# Short reads
# ---------------------------------------------------------------------------

# A fixed stream covering every length encoding, a fragmented pair with a
# control frame interleaved, and two different masks.
_SWEEP_FRAMES = (
    (_make_masked_frame(OP_TEXT, b"hello"), Frame(True, OP_TEXT, b"hello")),
    (
        _make_masked_frame(OP_BINARY, b"y" * 200),
        Frame(True, OP_BINARY, b"y" * 200),
    ),
    (
        _make_masked_frame(OP_BINARY, b"z" * 300, force_64bit_length=True),
        Frame(True, OP_BINARY, b"z" * 300),
    ),
    (
        _make_masked_frame(OP_TEXT, "héllo wörld".encode(), mask=b"\xde\xad\xbe\xef"),
        Frame(True, OP_TEXT, "héllo wörld".encode()),
    ),
    (
        _make_masked_frame(OP_TEXT, b"frag-", fin=False),
        Frame(False, OP_TEXT, b"frag-"),
    ),
    (
        _make_masked_frame(OP_PING, b"pingdata", mask=b"\x00\xff\x00\xff"),
        Frame(True, OP_PING, b"pingdata"),
    ),
    (
        _make_masked_frame(OP_CONTINUATION, b"ment"),
        Frame(True, OP_CONTINUATION, b"ment"),
    ),
    (
        _make_masked_frame(OP_CLOSE, struct.pack("!H", 1000) + b"bye"),
        Frame(True, OP_CLOSE, struct.pack("!H", 1000) + b"bye"),
    ),
)

SWEEP_STREAM = b"".join(data for data, _ in _SWEEP_FRAMES)
SWEEP_EXPECTED = [frame for _, frame in _SWEEP_FRAMES]


def test_short_read_sweep():
    """Every `recv` chunk size from 1 byte to the whole stream reads the same.

    This is the reader's whole reason for looping: a real socket hands back
    whatever happened to arrive, and a frame boundary can land anywhere.
    """

    async def run():
        for chunk in range(1, len(SWEEP_STREAM) + 1):
            recv = _Recv(SWEEP_STREAM, chunk=chunk)
            frames = [
                await read_frame(recv, MAX_PAYLOAD) for _ in range(len(SWEEP_EXPECTED))
            ]
            assert frames == SWEEP_EXPECTED, f"chunk size {chunk}"
            assert recv.handed_out == len(SWEEP_STREAM), f"chunk size {chunk}"
            with raises(IncompleteFrame):
                await read_frame(recv, MAX_PAYLOAD)

    asyncio.run(run())

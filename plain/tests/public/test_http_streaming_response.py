"""A file-like StreamingResponse body is read in blocks.

The server pulls each chunk of a sync stream with a trip to its thread
pool; iterating a file directly would make one trip per line.
"""

import io
import itertools
import os
import tempfile
import threading
from io import BytesIO, StringIO

from plain.http import FileResponse, StreamingResponse


def test_file_like_body_is_read_in_blocks() -> None:
    response = StreamingResponse(BytesIO(b"row\n" * 1000))

    assert list(response.streaming_content) == [b"row\n" * 1000]


def test_file_like_body_is_closed_with_the_response() -> None:
    body = BytesIO(b"data")
    response = StreamingResponse(body)

    response.close()

    assert body.closed


def test_pipe_body_streams_what_has_arrived() -> None:
    # A pipe has more coming: a block read would wait for 64KB or the end.
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "rb")
    os.write(write_fd, b"line 1\n")
    try:
        response = StreamingResponse(reader)
        chunks = iter(response.streaming_content)
        first: list[bytes] = []
        thread = threading.Thread(target=lambda: first.append(next(chunks)))
        thread.start()
        thread.join(timeout=2)
        assert first == [b"line 1\n"]
    finally:
        os.close(write_fd)
        reader.close()


def test_text_mode_file_response_ends() -> None:
    # A text file ends on "", not b"". Capped, so a body that never ends
    # fails here instead of hanging.
    response = FileResponse(StringIO("hello"), content_type="text/plain")

    assert list(itertools.islice(response.streaming_content, 3)) == [b"hello"]


class _ReadOnlyStream(io.BufferedIOBase):
    """Implements only `read` — its inherited `read1` raises."""

    def __init__(self, data: bytes) -> None:
        self._data = BytesIO(data)

    def readable(self) -> bool:
        return True

    def read(self, size: int | None = -1, /) -> bytes:
        return self._data.read(size)


def test_stream_without_a_working_read1_still_reads() -> None:
    response = StreamingResponse(_ReadOnlyStream(b"line 1\nline 2\n"))

    assert b"".join(response.streaming_content) == b"line 1\nline 2\n"


def test_file_response_without_a_working_read1_still_reads() -> None:
    response = FileResponse(_ReadOnlyStream(b"file bytes"), content_type="text/plain")

    assert b"".join(response.streaming_content) == b"file bytes"


def test_text_pipe_body_streams_line_by_line() -> None:
    # A text stream has no read1: it's read a line at a time as lines
    # arrive, not in a block that waits for 64KB or the end.
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "r")
    os.write(write_fd, b"line 1\n")
    try:
        response = StreamingResponse(reader)
        chunks = iter(response.streaming_content)
        first: list[bytes] = []
        thread = threading.Thread(target=lambda: first.append(next(chunks)))
        thread.start()
        thread.join(timeout=2)
        assert first == [b"line 1\n"]
    finally:
        os.close(write_fd)
        reader.close()


def test_unbuffered_binary_file_is_read_in_blocks(tmp_path) -> None:
    # No read1 on an unbuffered file: read(n) returns what's there, in
    # blocks — not a line (here, the whole newline-free file) at a time.
    path = tmp_path / "data.bin"
    path.write_bytes(b"x" * 200_000)
    with open(path, "rb", buffering=0) as raw:
        chunks = list(StreamingResponse(raw).streaming_content)

    assert b"".join(chunks) == b"x" * 200_000
    assert len(chunks) == 4


def test_text_mode_spooled_file_is_read() -> None:
    # A common CSV-export buffer: text mode, no TextIOBase.
    with tempfile.SpooledTemporaryFile(mode="w+") as spooled:
        spooled.write("a,b\n1,2\n")
        spooled.seek(0)

        assert list(StreamingResponse(spooled).streaming_content) == [b"a,b\n1,2\n"]


def test_regular_text_file_is_read_in_blocks(tmp_path) -> None:
    # Seekable text is read in blocks, not one pool trip per line.
    path = tmp_path / "export.csv"
    path.write_text("row\n" * 1000)
    with open(path) as text_file:
        chunks = list(StreamingResponse(text_file).streaming_content)

    assert chunks == [b"row\n" * 1000]

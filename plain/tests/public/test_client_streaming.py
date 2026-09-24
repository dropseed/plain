"""The test client reads a sync streaming body the way a server does.

It used to close the response before handing it back, which closed a
generator body before the test could read it — so a test of a streamed
download saw an empty (or closed-file) body.
"""

import pytest
from plain.test import Client


def test_generator_body_is_readable() -> None:
    response = Client().get("/stream-generator")

    assert response.status_code == 200
    assert response.content == b"line 1\nline 2\n"


def test_file_like_body_is_readable() -> None:
    response = Client().get("/stream")

    assert response.content == b"streamed-bytes"


def test_streaming_response_keeps_its_type() -> None:
    response = Client().get("/stream-generator")

    assert response.streaming


def test_head_does_not_read_the_body() -> None:
    response = Client().head("/stream-generator")

    assert response.content == b""


def test_body_error_is_raised() -> None:
    with pytest.raises(ValueError, match="export failed"):
        Client().get("/stream-fails")


def test_body_error_without_raising_keeps_what_came_before() -> None:
    response = Client(raise_request_exception=False).get("/stream-fails")

    assert isinstance(response.exception, ValueError)
    assert response.content == b"line 1\n"


def test_async_body_error_without_raising_keeps_what_came_before() -> None:
    response = Client(raise_request_exception=False).get("/async-stream-fails")

    assert isinstance(response.exception, ValueError)
    assert response.content == b"data: 1\n\n"


def test_file_response_stays_a_file_response() -> None:
    response = Client().get("/file")

    assert response.content == b"file bytes"
    assert response.file_to_stream is not None


def test_body_failing_before_its_first_chunk_is_a_500() -> None:
    # What a server sends: the headers go out with the first chunk, so a
    # body that fails before one is answered with a 500.
    response = Client(raise_request_exception=False).get("/stream-fails-first")

    assert response.status_code == 500
    assert response.content == b""
    assert isinstance(response.exception, ValueError)


def test_streaming_content_points_to_content() -> None:
    response = Client().get("/stream-generator")

    with pytest.raises(AttributeError, match="response.content"):
        _ = response.streaming_content

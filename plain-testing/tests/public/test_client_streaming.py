"""The test client reads a sync streaming body the way a server does.

It used to close the response before handing it back, which closed a
generator body before the test could read it — so a test of a streamed
download saw an empty (or closed-file) body.
"""

from plain.http import FileResponse, StreamingResponse
from plain.testing import Client, cases, raises


def test_generator_body_is_readable() -> None:
    response = Client().get("/stream-generator")

    assert response.status_code == 200
    assert response.body == b"line 1\nline 2\n"


def test_file_like_body_is_readable() -> None:
    response = Client().get("/stream")

    assert response.body == b"streamed-bytes"


def test_returned_response_is_the_object_the_view_returned() -> None:
    response = Client().get("/stream-generator")

    assert isinstance(response.returned_response, StreamingResponse)


def test_head_does_not_read_the_body() -> None:
    response = Client().head("/stream-generator")

    assert response.body == b""


def test_body_error_is_raised() -> None:
    with raises(ValueError, match="export failed"):
        Client().get("/stream-fails")


def test_body_error_without_raising_keeps_what_came_before() -> None:
    response = Client(raise_exceptions=False).get("/stream-fails")

    assert isinstance(response.exception, ValueError)
    assert response.body == b"line 1\n"


def test_async_body_error_without_raising_keeps_what_came_before() -> None:
    response = Client(raise_exceptions=False).get("/async-stream-fails")

    assert isinstance(response.exception, ValueError)
    assert response.body == b"data: 1\n\n"


def test_file_response_stays_a_file_response() -> None:
    response = Client().get("/file")

    assert response.body == b"file bytes"
    assert isinstance(response.returned_response, FileResponse)


def test_body_failing_before_its_first_chunk_is_a_500() -> None:
    # What a server sends: the headers go out with the first chunk, so a
    # body that fails before one is answered with a 500.
    response = Client(raise_exceptions=False).get("/stream-fails-first")

    assert response.status_code == 500
    assert response.body == b""
    assert isinstance(response.exception, ValueError)


@cases(
    "content",
    "streaming_content",
    "streaming",
    "resolver_match",
    "url",
    "reason_phrase",
    "charset",
)
def test_a_name_the_returned_response_has_is_not_forwarded(name: str) -> None:
    # Each of these is an attribute of the Response the view returned. The
    # client's response has its own fixed names and forwards none of them.
    response = Client().get("/stream-generator")

    with raises(AttributeError) as caught:
        getattr(response, name)

    message = str(caught.exception)
    assert f"has no `{name}`" in message
    assert "status_code, headers, cookies, body, text, json_data" in message
    assert "response.returned_response" in message


def test_text_and_body_read_the_sent_body() -> None:
    response = Client().get("/stream-generator")

    assert response.text == "line 1\nline 2\n"
    assert response.body == b"line 1\nline 2\n"


def test_head_of_a_buffered_response_has_no_body() -> None:
    # The wrapped response still holds what a GET would have sent; the
    # client reports what went out.
    response = Client().head("/")

    assert response.body == b""
    assert response.text == ""

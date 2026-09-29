"""A `Request` is constructed with its body.

The server and everything that builds a request in-process go through the
same constructor, so what these pin is what a view sees either way.
"""

import json
from io import BytesIO

from plain.http import RawPostDataException, Request
from plain.testing import raises


def test_a_request_without_a_body_has_an_empty_one():
    request = Request(method="GET", path="/")

    assert request.body == b""
    assert request.read() == b""


def test_bytes_are_the_body():
    request = Request(method="POST", path="/", body=b"hello")

    assert request.body == b"hello"


def test_a_stream_is_read_as_the_body():
    request = Request(method="POST", path="/", body=BytesIO(b"from a stream"))

    assert request.body == b"from a stream"


def test_the_body_can_be_read_as_a_stream():
    request = Request(method="POST", path="/", body=b"first\nsecond\n")

    assert request.readline() == b"first\n"
    assert request.read() == b"second\n"


def test_body_is_refused_once_the_stream_has_been_read():
    request = Request(method="POST", path="/", body=b"hello")
    request.read(1)

    with raises(RawPostDataException):
        _ = request.body


def test_form_data_is_parsed_from_the_body():
    body = b"name=Ada&language=python"
    request = Request(
        method="POST",
        path="/",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body)),
        },
        body=body,
    )

    assert request.form_data["name"] == "Ada"
    assert request.form_data["language"] == "python"


def test_json_data_is_parsed_from_the_body():
    body = json.dumps({"name": "Ada"}).encode()
    request = Request(
        method="POST",
        path="/",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
        body=body,
    )

    assert request.json_data == {"name": "Ada"}


def test_files_are_parsed_from_a_multipart_body():
    boundary = "TeStBoUnDaRy"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="upload"; filename="notes.txt"\r\n'
        "Content-Type: text/plain\r\n"
        "\r\n"
        "file contents\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    request = Request(
        method="POST",
        path="/",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        body=body,
    )

    upload = request.files["upload"]
    assert upload.name == "notes.txt"
    assert upload.read() == b"file contents"


def test_body_ingest_seconds_is_none_unless_given():
    assert Request(method="GET", path="/").body_ingest_seconds is None

    request = Request(method="POST", path="/", body=b"x", body_ingest_seconds=0.25)
    assert request.body_ingest_seconds == 0.25

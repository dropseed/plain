"""Change detectors for `plain.http.multipartparser.MultiPartParser`.

These feed hand-built multipart bytes straight to the parser, below the
request/response layer that `tests/public/test_file_uploads.py` covers.
Several of them pin behavior that looks wrong — malformed input tends to
be swallowed rather than reported. Each of those says so; the assertion is
"this is what happens today", not "this is what should happen".
"""

from __future__ import annotations

from io import BytesIO

import pytest
from plain.http import Request
from plain.http.multipartparser import MultiPartParser, MultiPartParserError
from plain.utils.datastructures import MultiValueDict

BOUNDARY = "TeStBoUnDaRy"
MULTIPART_CONTENT_TYPE = f"multipart/form-data; boundary={BOUNDARY}"

# `Parser.__iter__` hands `_parse_boundary_stream` a fixed 1024-byte budget
# for a part's headers. It is not a setting and there is no way to raise it.
MAX_PART_HEADER_SIZE = 1024


def _parse(
    body: bytes, *, content_type: str = MULTIPART_CONTENT_TYPE
) -> tuple[dict[str, list[str]], MultiValueDict]:
    """Parse `body` and return the POST data as a plain dict, plus FILES."""
    request = Request(
        method="POST",
        path="/",
        headers={"Content-Type": content_type, "Content-Length": str(len(body))},
    )
    request._stream = BytesIO(body)
    post, files = MultiPartParser(request).parse()
    return dict(post.lists()), files


def _file_contents(files: MultiValueDict) -> dict[str, list[tuple[str, bytes]]]:
    return {
        field_name: [(uploaded.name, uploaded.read()) for uploaded in uploads]
        for field_name, uploads in files.lists()
    }


def test_well_formed_body_is_the_baseline():
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="note"\r\n'
        "\r\n"
        "hello\r\n"
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="doc"; filename="x.txt"\r\n'
        "Content-Type: text/plain\r\n"
        "\r\n"
        "contents\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    post, files = _parse(body)

    assert post == {"note": ["hello"]}
    assert _file_contents(files) == {"doc": [("x.txt", b"contents")]}


def test_empty_body_parses_as_empty():
    """Content-Length 0 short-circuits before any stream reading."""
    post, files = _parse(b"")

    assert post == {}
    assert files == MultiValueDict()


# Malformed input


def test_missing_final_boundary_keeps_the_trailing_crlf_in_the_field_value():
    """An unterminated field silently absorbs its own line ending.

    A well-formed body strips the CRLF that precedes the closing boundary.
    With no closing boundary there is nothing to strip against, so the CRLF
    ends up inside the value. Nothing is raised. This looks like a bug.
    """
    body = (
        f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="note"\r\n\r\nhello\r\n'
    ).encode()

    post, files = _parse(body)

    assert post == {"note": ["hello\r\n"]}
    assert files == MultiValueDict()


def test_missing_final_boundary_silently_drops_the_file():
    """An unterminated file part disappears entirely — no file, no error.

    The parser only completes a file when it reaches the *next* boundary, so
    a truncated upload (client disconnect, cut-off proxy) is indistinguishable
    from a request that never sent the file. This looks like a bug.
    """
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="doc"; filename="x.txt"\r\n'
        "\r\n"
        "contents"
    ).encode()

    post, files = _parse(body)

    assert post == {}
    assert files == MultiValueDict()


def test_garbage_after_the_final_boundary_is_ignored():
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="note"\r\n'
        "\r\n"
        "hello\r\n"
        f"--{BOUNDARY}--\r\n"
        "GARBAGE GARBAGE GARBAGE\r\n"
    ).encode()

    post, files = _parse(body)

    assert post == {"note": ["hello"]}
    assert files == MultiValueDict()


def test_part_without_content_disposition_is_skipped():
    """No Content-Disposition means no field name, so the part is dropped."""
    body = (
        f"--{BOUNDARY}\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "orphaned\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    post, files = _parse(body)

    assert post == {}
    assert files == MultiValueDict()


def test_body_that_is_not_multipart_at_all_parses_as_empty():
    """No boundary anywhere in the body is not an error."""
    post, files = _parse(b"this is not multipart at all")

    assert post == {}
    assert files == MultiValueDict()


def test_lf_only_line_endings_parse_as_empty():
    """The parser requires CRLF; an LF-only body yields nothing, silently."""
    body = (
        f"--{BOUNDARY}\n"
        'Content-Disposition: form-data; name="note"\n'
        "\n"
        "hello\n"
        f"--{BOUNDARY}--\n"
    ).encode()

    post, files = _parse(body)

    assert post == {}
    assert files == MultiValueDict()


# Content-Transfer-Encoding


def test_base64_transfer_encoding_decodes_a_field():
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="note"\r\n'
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        "aGVsbG8=\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    post, _ = _parse(body)

    assert post == {"note": ["hello"]}


def test_base64_transfer_encoding_decodes_a_file():
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="doc"; filename="x.txt"\r\n'
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        "aGVsbG8gd29ybGQ=\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    _, files = _parse(body)

    assert _file_contents(files) == {"doc": [("x.txt", b"hello world")]}


def test_undecodable_base64_field_falls_back_to_the_raw_bytes():
    """A field that claims base64 but isn't comes through undecoded."""
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="note"\r\n'
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        "!!!notbase64!!!\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    post, _ = _parse(body)

    assert post == {"note": ["!!!notbase64!!!"]}


def test_quoted_printable_transfer_encoding_is_not_decoded():
    """base64 is the only transfer encoding the parser understands.

    Anything else passes through verbatim rather than being rejected, so a
    quoted-printable field arrives with its escape sequences intact.
    """
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="note"\r\n'
        "Content-Transfer-Encoding: quoted-printable\r\n"
        "\r\n"
        "hello=20world\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    post, _ = _parse(body)

    assert post == {"note": ["hello=20world"]}


# Per-part header size


def test_part_headers_just_under_the_limit_parse():
    padding = "x" * (MAX_PART_HEADER_SIZE - 200)
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="note"\r\n'
        f"X-Padding: {padding}\r\n"
        "\r\n"
        "hello\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    post, _ = _parse(body)

    assert post == {"note": ["hello"]}


def test_part_headers_over_the_limit_silently_drop_the_part():
    """Headers past 1024 bytes make the part vanish — no field, no error.

    `_parse_boundary_stream` looks for the header terminator only within
    its 1024-byte budget; not finding one, it classifies the part as raw
    padding and discards it. Later parts are unaffected.
    """
    padding = "x" * (MAX_PART_HEADER_SIZE * 2)
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="dropped"\r\n'
        f"X-Padding: {padding}\r\n"
        "\r\n"
        "hello\r\n"
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="kept"\r\n'
        "\r\n"
        "world\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    post, _ = _parse(body)

    assert post == {"kept": ["world"]}


# Boundary parameter


def test_quoted_boundary_parameter_is_accepted():
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="note"\r\n'
        "\r\n"
        "hello\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    post, _ = _parse(body, content_type=f'multipart/form-data; boundary="{BOUNDARY}"')

    assert post == {"note": ["hello"]}


@pytest.mark.parametrize("length", [1, 201])
def test_boundary_up_to_201_characters_is_accepted(length: int):
    boundary = "a" * length
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="note"\r\n'
        "\r\n"
        "hello\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    post, _ = _parse(body, content_type=f"multipart/form-data; boundary={boundary}")

    assert post == {"note": ["hello"]}


def test_boundary_over_201_characters_is_rejected():
    boundary = "a" * 202

    with pytest.raises(MultiPartParserError, match="Invalid boundary"):
        _parse(b"", content_type=f"multipart/form-data; boundary={boundary}")


@pytest.mark.parametrize(
    "content_type",
    [
        "",
        "text/plain",
        "application/x-www-form-urlencoded",
    ],
)
def test_non_multipart_content_type_is_rejected(content_type: str):
    with pytest.raises(MultiPartParserError, match="Invalid Content-Type"):
        _parse(b"", content_type=content_type)


@pytest.mark.parametrize(
    "content_type",
    [
        "multipart/form-data",
        'multipart/form-data; boundary=""',
    ],
)
def test_missing_boundary_parameter_is_rejected(content_type: str):
    with pytest.raises(MultiPartParserError, match="Invalid boundary"):
        _parse(b"", content_type=content_type)


def test_non_ascii_boundary_is_rejected_by_the_boundary_check():
    """The boundary regex only admits printable ASCII.

    Note which check fires: the parser's non-ASCII guard inspects
    `request.content_type`, which the request has already stripped of its
    parameters, so a non-ASCII boundary never reaches it. That guard is
    unreachable from a header-derived content type.
    """
    with pytest.raises(MultiPartParserError, match="Invalid boundary"):
        _parse(b"", content_type="multipart/form-data; boundary=héllo")


# Filenames


def test_filename_keeps_non_ascii_characters():
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="doc"; filename="héllo-世界.txt"\r\n'
        "\r\n"
        "contents\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    _, files = _parse(body)

    assert _file_contents(files) == {"doc": [("héllo-世界.txt", b"contents")]}


@pytest.mark.parametrize(
    ("sent", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        (r"C:\Windows\evil.exe", "evil.exe"),
        ("plain\x00hidden.txt", "plainhidden.txt"),
    ],
)
def test_filename_is_sanitized(sent: str, expected: str):
    body = (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="doc"; filename="{sent}"\r\n'
        "\r\n"
        "contents\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    _, files = _parse(body)

    assert _file_contents(files) == {"doc": [(expected, b"contents")]}


def test_file_part_without_a_content_type_reports_an_empty_string():
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="doc"; filename="x.bin"\r\n'
        "\r\n"
        "contents\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    _, files = _parse(body)

    assert files["doc"].content_type == ""

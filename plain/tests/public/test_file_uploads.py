from __future__ import annotations

import hashlib
import random
from io import BytesIO

from plain.runtime import settings
from plain.test import Client

BOUNDARY = "TeStBoUnDaRy"
MULTIPART_CONTENT_TYPE = f"multipart/form-data; boundary={BOUNDARY}"


class UploadPayload(BytesIO):
    """A file-like shaped the way the test client's multipart encoder expects.

    The encoder reads `name` for the filename and, when it's set, `content_type`
    for the part's Content-Type. Leaving `content_type` unset is meaningful —
    that's what makes the encoder guess the type from the filename.
    """

    name: str
    content_type: str

    def __init__(self, name: str, content: bytes, *, content_type: str | None = None):
        super().__init__(content)
        self.name = name
        if content_type is not None:
            self.content_type = content_type


def _upload(size: int):
    client = Client()
    return client.post(
        "/upload", data={"upload": UploadPayload("upload.bin", b"x" * size)}
    )


def _post_raw_multipart(body: bytes):
    """POST a hand-built multipart body the test client's encoder can't express."""
    client = Client()
    return client.post(
        "/multipart-echo", data=body, content_type=MULTIPART_CONTENT_TYPE
    )


def test_small_upload_stays_in_memory():
    """Uploads under FILE_UPLOAD_MAX_MEMORY_SIZE are buffered in memory."""
    size = 1024
    assert size < settings.FILE_UPLOAD_MAX_MEMORY_SIZE

    response = _upload(size)

    assert response.status_code == 200
    assert response.content == f"InMemoryUploadedFile:{size}".encode()


def test_large_upload_streams_to_temp_file():
    """Uploads over FILE_UPLOAD_MAX_MEMORY_SIZE stream to disk.

    This path is served by a separate upload handler than the small-file
    path, so a small-upload test alone leaves it uncovered.
    """
    size = settings.FILE_UPLOAD_MAX_MEMORY_SIZE + 1024

    response = _upload(size)

    assert response.status_code == 200
    assert response.content == f"TemporaryUploadedFile:{size}".encode()


def test_body_over_data_upload_limit_is_413():
    """Reading a body larger than DATA_UPLOAD_MAX_MEMORY_SIZE is a 413."""
    client = Client()
    body = b"x" * (settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1)

    response = client.post("/echo-body", data=body, content_type="text/plain")

    assert response.status_code == 413


def test_multiple_files_under_distinct_field_names():
    client = Client()

    response = client.post(
        "/multipart-echo",
        data={
            "first": UploadPayload("one.txt", b"AAA"),
            "second": UploadPayload("two.txt", b"BBBB"),
        },
    )

    assert response.status_code == 200
    files = response.json()["files"]
    assert [(f["field_name"], f["name"], f["size"]) for f in files] == [
        ("first", "one.txt", 3),
        ("second", "two.txt", 4),
    ]


def test_multiple_files_under_one_field_name():
    """Repeating a field name keeps every file, in order."""
    client = Client()

    response = client.post(
        "/multipart-echo",
        data={
            "attachment": [
                UploadPayload("one.txt", b"AAA"),
                UploadPayload("two.txt", b"BBBB"),
            ]
        },
    )

    assert response.status_code == 200
    files = response.json()["files"]
    assert [(f["field_name"], f["name"]) for f in files] == [
        ("attachment", "one.txt"),
        ("attachment", "two.txt"),
    ]


def test_files_and_form_fields_in_one_request():
    """A mixed request populates form_data and files independently."""
    client = Client()

    response = client.post(
        "/multipart-echo",
        data={
            "title": "Some title",
            "tags": ["a", "b"],
            "document": UploadPayload("doc.txt", b"contents"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["form_data"] == {"title": ["Some title"], "tags": ["a", "b"]}
    assert [(f["field_name"], f["name"]) for f in body["files"]] == [
        ("document", "doc.txt")
    ]


def test_large_file_content_round_trips_byte_for_byte():
    """A multi-chunk upload arrives with its bytes unchanged.

    The size puts it past FILE_UPLOAD_MAX_MEMORY_SIZE (so it streams to a
    temporary file) and well past the 64 KB read chunk, so boundary
    detection has to stitch many chunks back together.
    """
    size = settings.FILE_UPLOAD_MAX_MEMORY_SIZE + 4096
    content = random.Random(0).randbytes(size)
    client = Client()

    response = client.post(
        "/multipart-echo", data={"blob": UploadPayload("blob.bin", content)}
    )

    assert response.status_code == 200
    (uploaded,) = response.json()["files"]
    assert uploaded["handler"] == "TemporaryUploadedFile"
    assert uploaded["size"] == size
    assert uploaded["sha256"] == hashlib.sha256(content).hexdigest()


def test_binary_content_with_crlf_round_trips_byte_for_byte():
    """CRLF runs inside file content aren't mistaken for part separators."""
    content = b"\r\n--not-the-boundary\r\n\x00\xff\r\n" * 100
    client = Client()

    response = client.post(
        "/multipart-echo", data={"blob": UploadPayload("blob.bin", content)}
    )

    assert response.status_code == 200
    (uploaded,) = response.json()["files"]
    assert uploaded["size"] == len(content)
    assert uploaded["sha256"] == hashlib.sha256(content).hexdigest()


def test_unicode_filename_is_preserved():
    client = Client()

    response = client.post(
        "/multipart-echo", data={"doc": UploadPayload("héllo-世界.txt", b"hi")}
    )

    assert response.status_code == 200
    (uploaded,) = response.json()["files"]
    assert uploaded["name"] == "héllo-世界.txt"


def test_per_part_content_type_is_surfaced():
    client = Client()

    response = client.post(
        "/multipart-echo",
        data={"doc": UploadPayload("rows.csv", b"a,b", content_type="text/csv")},
    )

    assert response.status_code == 200
    (uploaded,) = response.json()["files"]
    assert uploaded["content_type"] == "text/csv"


def test_per_part_charset_is_surfaced_as_bytes():
    """`UploadedFile.charset` comes back as bytes, not str.

    Every content-type parameter is byte-encoded on its way out of the
    parser, so app code comparing `uploaded.charset == "utf-16"` silently
    never matches. Pinned as-is.
    """
    client = Client()

    response = client.post(
        "/multipart-echo",
        data={
            "doc": UploadPayload(
                "rows.csv", b"a,b", content_type="text/csv; charset=utf-16"
            )
        },
    )

    assert response.status_code == 200
    (uploaded,) = response.json()["files"]
    assert uploaded["content_type"] == "text/csv"
    assert uploaded["charset_repr"] == "b'utf-16'"


def test_file_part_with_empty_filename_becomes_a_form_field():
    """A `filename=""` part lands in form_data, not files.

    Browsers send this for a file input the user left empty. The part's
    body becomes the field's string value, so an empty file input shows up
    as an empty string rather than being dropped.
    """
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="doc"; filename=""\r\n'
        "Content-Type: application/octet-stream\r\n"
        "\r\n"
        "\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    response = _post_raw_multipart(body)

    assert response.status_code == 200
    assert response.json() == {"form_data": {"doc": [""]}, "files": []}


def test_filename_of_only_path_separators_drops_the_part():
    """`filename="../"` sanitizes down to nothing, and the part disappears.

    It shows up in neither form_data nor files — the parser has already
    committed to treating it as a file by the time the name is rejected.
    """
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="doc"; filename="../"\r\n'
        "\r\n"
        "contents\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    response = _post_raw_multipart(body)

    assert response.status_code == 200
    assert response.json() == {"form_data": {}, "files": []}


def test_filename_directory_components_are_stripped():
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="doc"; '
        'filename="../../etc/passwd"\r\n'
        "\r\n"
        "contents\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()

    response = _post_raw_multipart(body)

    assert response.status_code == 200
    (uploaded,) = response.json()["files"]
    assert uploaded["name"] == "passwd"


def test_too_many_fields_is_400(monkeypatch):
    monkeypatch.setattr(settings, "DATA_UPLOAD_MAX_NUMBER_FIELDS", 2)
    client = Client()

    response = client.post(
        "/multipart-echo", data={f"field{i}": "value" for i in range(10)}
    )

    assert response.status_code == 400


def test_field_count_at_the_limit_is_allowed(monkeypatch):
    monkeypatch.setattr(settings, "DATA_UPLOAD_MAX_NUMBER_FIELDS", 2)
    client = Client()

    response = client.post("/multipart-echo", data={"a": "1", "b": "2"})

    assert response.status_code == 200
    assert response.json()["form_data"] == {"a": ["1"], "b": ["2"]}


def test_too_many_files_is_400(monkeypatch):
    monkeypatch.setattr(settings, "DATA_UPLOAD_MAX_NUMBER_FILES", 1)
    client = Client()

    response = client.post(
        "/multipart-echo",
        data={
            "attachment": [
                UploadPayload("one.txt", b"AAA"),
                UploadPayload("two.txt", b"BBB"),
            ]
        },
    )

    assert response.status_code == 400


def test_file_count_at_the_limit_is_allowed(monkeypatch):
    monkeypatch.setattr(settings, "DATA_UPLOAD_MAX_NUMBER_FILES", 1)
    client = Client()

    response = client.post(
        "/multipart-echo", data={"attachment": UploadPayload("one.txt", b"AAA")}
    )

    assert response.status_code == 200
    assert len(response.json()["files"]) == 1


def test_form_field_over_data_upload_max_memory_size_is_413(monkeypatch):
    """Non-file field data is capped by DATA_UPLOAD_MAX_MEMORY_SIZE.

    Files are exempt — they stream to disk — so the same request with the
    payload in a file part succeeds (see the companion test below).
    """
    monkeypatch.setattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 100)
    client = Client()

    response = client.post("/multipart-echo", data={"note": "x" * 500})

    assert response.status_code == 413


def test_file_part_is_not_capped_by_data_upload_max_memory_size(monkeypatch):
    monkeypatch.setattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 100)
    client = Client()

    response = client.post(
        "/multipart-echo", data={"doc": UploadPayload("big.txt", b"x" * 500)}
    )

    assert response.status_code == 200
    (uploaded,) = response.json()["files"]
    assert uploaded["size"] == 500

from __future__ import annotations

from io import BytesIO

from plain.runtime import settings
from plain.test import Client


def _upload(size: int):
    client = Client()
    payload = BytesIO(b"x" * size)
    payload.name = "upload.bin"
    return client.post("/upload", data={"upload": payload})


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

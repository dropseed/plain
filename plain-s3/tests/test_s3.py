from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from plain.s3.models import S3File


@pytest.fixture
def mock_s3_client():
    """Mock the boto3 S3 client."""
    with patch("plain.s3.models.boto3.client") as mock_client:
        client = MagicMock()
        mock_client.return_value = client
        yield client


@pytest.fixture
def s3_file(db):
    """Create a test S3File record."""
    return S3File.query.create(
        bucket="test-bucket",
        key="abc123.pdf",
        filename="document.pdf",
        content_type="application/pdf",
        byte_size=1024,
    )


class TestGenerateKey:
    def test_generates_unique_keys(self):
        key1 = S3File._generate_key("test.pdf")
        key2 = S3File._generate_key("test.pdf")
        assert key1 != key2

    def test_preserves_extension(self):
        key = S3File._generate_key("document.pdf")
        assert key.endswith(".pdf")

    def test_lowercases_extension(self):
        key = S3File._generate_key("document.PDF")
        assert key.endswith(".pdf")

    def test_handles_no_extension(self):
        key = S3File._generate_key("README")
        assert "." not in key

    def test_applies_key_prefix(self):
        key = S3File._generate_key("test.pdf", key_prefix="uploads/")
        assert key.startswith("uploads/")
        assert key.endswith(".pdf")


class TestUpload:
    def test_uploads_file_to_s3(self, db, mock_s3_client):
        file = BytesIO(b"test content")
        file.name = "test.txt"

        S3File.upload(file=file)

        mock_s3_client.put_object.assert_called_once()
        call_kwargs = mock_s3_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Body"] == b"test content"
        assert call_kwargs["ContentType"] == "text/plain"

    def test_creates_database_record(self, db, mock_s3_client):
        file = BytesIO(b"test content")
        file.name = "test.txt"

        s3_file = S3File.upload(file=file)

        assert s3_file.id is not None
        assert s3_file.filename == "test.txt"
        assert s3_file.byte_size == 12
        assert s3_file.content_type == "text/plain"

    def test_uses_custom_bucket(self, db, mock_s3_client):
        file = BytesIO(b"test")
        file.name = "test.txt"

        s3_file = S3File.upload(file=file, bucket="custom-bucket")

        call_kwargs = mock_s3_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "custom-bucket"
        assert s3_file.bucket == "custom-bucket"

    def test_applies_acl(self, db, mock_s3_client):
        file = BytesIO(b"test")
        file.name = "test.txt"

        S3File.upload(file=file, acl="public-read")

        call_kwargs = mock_s3_client.put_object.call_args.kwargs
        assert call_kwargs["ACL"] == "public-read"


class TestCreatePresignedUpload:
    def test_creates_presigned_url(self, db, mock_s3_client):
        mock_s3_client.generate_presigned_url.return_value = (
            "https://s3.example.com/presigned-url"
        )

        result = S3File.create_presigned_upload(
            filename="document.pdf",
            byte_size=1024,
        )

        assert "key" in result
        assert result["upload_url"] == "https://s3.example.com/presigned-url"
        mock_s3_client.generate_presigned_url.assert_called_once()

    def test_creates_database_record(self, db, mock_s3_client):
        mock_s3_client.generate_presigned_url.return_value = (
            "https://s3.example.com/presigned-url"
        )

        result = S3File.create_presigned_upload(
            filename="document.pdf",
            byte_size=1024,
        )

        s3_file = S3File.query.get(key=result["key"])
        assert s3_file.filename == "document.pdf"
        assert s3_file.byte_size == 1024


class TestPresignedDownloadUrl:
    def test_generates_download_url(self, s3_file, mock_s3_client):
        mock_s3_client.generate_presigned_url.return_value = "https://signed-url"

        url = s3_file.presigned_download_url()

        assert url == "https://signed-url"
        call_args = mock_s3_client.generate_presigned_url.call_args
        params = call_args.kwargs["Params"]
        assert (
            'attachment; filename="document.pdf"'
            in params["ResponseContentDisposition"]
        )

    def test_inline_disposition(self, s3_file, mock_s3_client):
        mock_s3_client.generate_presigned_url.return_value = "https://signed-url"

        s3_file.presigned_download_url(inline=True)

        call_args = mock_s3_client.generate_presigned_url.call_args
        params = call_args.kwargs["Params"]
        assert 'inline; filename="document.pdf"' in params["ResponseContentDisposition"]

    def test_custom_expiration(self, s3_file, mock_s3_client):
        mock_s3_client.generate_presigned_url.return_value = "https://signed-url"

        s3_file.presigned_download_url(expires_in=7200)

        call_args = mock_s3_client.generate_presigned_url.call_args
        assert call_args.kwargs["ExpiresIn"] == 7200


class TestExistsInStorage:
    def test_returns_true_when_exists(self, s3_file, mock_s3_client):
        mock_s3_client.head_object.return_value = {}

        assert s3_file.exists_in_storage() is True

    def test_returns_false_when_not_exists(self, s3_file, mock_s3_client):
        error = MagicMock()
        error.response = {"Error": {"Code": "404"}}
        mock_s3_client.head_object.side_effect = mock_s3_client.exceptions.ClientError(
            error.response, "HeadObject"
        )
        mock_s3_client.exceptions.ClientError = type(
            "ClientError",
            (Exception,),
            {"response": property(lambda self: error.response)},
        )

        # Re-raise the mock exception
        mock_s3_client.head_object.side_effect = mock_s3_client.exceptions.ClientError(
            error.response, "HeadObject"
        )

        assert s3_file.exists_in_storage() is False


class TestDelete:
    def test_deletes_from_s3_and_database(self, s3_file, mock_s3_client):
        file_id = s3_file.id

        s3_file.delete()

        mock_s3_client.delete_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="abc123.pdf",
        )
        assert S3File.query.filter(id=file_id).count() == 0


class TestProperties:
    def test_extension(self, s3_file):
        assert s3_file.extension == "pdf"

    def test_extension_no_dot(self, db):
        file = S3File.query.create(
            bucket="test",
            key="abc",
            filename="README",
            content_type="text/plain",
            byte_size=100,
        )
        assert file.extension == ""

    def test_size_display_bytes(self, db):
        file = S3File.query.create(
            bucket="test",
            key="abc",
            filename="test",
            content_type="text/plain",
            byte_size=500,
        )
        assert file.size_display == "500 B"

    def test_size_display_kb(self, db):
        file = S3File.query.create(
            bucket="test",
            key="abc",
            filename="test",
            content_type="text/plain",
            byte_size=2048,
        )
        assert file.size_display == "2.0 KB"

    def test_str(self, s3_file):
        assert str(s3_file) == "document.pdf"

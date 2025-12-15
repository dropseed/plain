from __future__ import annotations

import mimetypes
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypedDict
from uuid import uuid4

import boto3

from plain import models
from plain.models import types
from plain.runtime import settings

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client


class PresignedUpload(TypedDict):
    """Return type for create_presigned_upload."""

    key: str
    upload_url: str


@models.register_model
class S3File(models.Model):
    """
    Represents a file stored in S3-compatible storage.

    This model stores metadata about files. The actual file content
    is stored in S3. Link to this model using S3FileField() on your models.
    """

    query: models.QuerySet[S3File] = models.QuerySet()

    # S3 storage location
    bucket: str = types.CharField(max_length=255)
    key: str = types.CharField(max_length=500)

    # File metadata
    filename: str = types.CharField(max_length=255)
    content_type: str = types.CharField(max_length=100)
    byte_size: int = types.PositiveBigIntegerField()

    created_at: datetime = types.DateTimeField(auto_now_add=True)

    model_options = models.Options(
        indexes=[
            models.Index(fields=["created_at"]),
        ],
        constraints=[
            models.UniqueConstraint(fields=["key"], name="plains3_s3file_unique_key"),
        ],
    )

    def __str__(self) -> str:
        return self.filename

    @classmethod
    def get_s3_client(cls) -> S3Client:
        """Create an S3 client using settings."""
        kwargs: dict[str, Any] = {
            "aws_access_key_id": settings.S3_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.S3_SECRET_ACCESS_KEY,
            "region_name": settings.S3_REGION,
        }
        if settings.S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        return boto3.client("s3", **kwargs)

    @classmethod
    def _generate_key(cls, filename: str, *, key_prefix: str = "") -> str:
        """Generate a unique S3 key for a new file."""
        ext = ""
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower()
        return f"{key_prefix}{uuid4()}{ext}"

    @classmethod
    def upload(
        cls,
        *,
        file: Any,
        bucket: str = "",
        key_prefix: str = "",
        acl: str = "",
    ) -> S3File:
        """
        Upload a file to S3 and create the S3File record.
        """
        bucket = bucket or settings.S3_BUCKET
        filename = file.name
        content_type = getattr(file, "content_type", None)
        if content_type is None:
            content_type, _ = mimetypes.guess_type(filename)
            content_type = content_type or "application/octet-stream"

        key = cls._generate_key(filename, key_prefix=key_prefix)
        body = file.read()
        byte_size = len(body)

        # Upload to S3
        client = cls.get_s3_client()
        put_kwargs = {
            "Bucket": bucket,
            "Key": key,
            "Body": body,
            "ContentType": content_type,
        }
        if acl:
            put_kwargs["ACL"] = acl
        client.put_object(**put_kwargs)

        # Create the database record
        return cls.query.create(
            bucket=bucket,
            key=key,
            filename=filename,
            content_type=content_type,
            byte_size=byte_size,
        )

    @classmethod
    def create_presigned_upload(
        cls,
        *,
        filename: str,
        byte_size: int,
        bucket: str = "",
        content_type: str | None = None,
        key_prefix: str = "",
        acl: str = "",
    ) -> PresignedUpload:
        """
        Create a new S3File record and return presigned upload data.

        The file record is created immediately but the file isn't uploaded yet.
        After the client uploads directly to S3, the file will be available.
        """
        bucket = bucket or settings.S3_BUCKET

        if content_type is None:
            content_type, _ = mimetypes.guess_type(filename)
            content_type = content_type or "application/octet-stream"

        key = cls._generate_key(filename, key_prefix=key_prefix)

        # Create the file record
        cls.query.create(
            bucket=bucket,
            key=key,
            filename=filename,
            content_type=content_type,
            byte_size=byte_size,
        )

        client = cls.get_s3_client()

        params: dict[str, Any] = {
            "Bucket": bucket,
            "Key": key,
            "ContentType": content_type,
        }
        if acl:
            params["ACL"] = acl

        upload_url = client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=3600,
        )

        return PresignedUpload(
            key=key,
            upload_url=upload_url,
        )

    def presigned_download_url(
        self, *, expires_in: int = 3600, inline: bool = False
    ) -> str:
        """Generate a presigned URL for downloading this file.

        Use inline=True to display in browser (for images, PDFs, etc.)
        instead of triggering a download.
        """
        client = self.get_s3_client()
        disposition = "inline" if inline else "attachment"
        params = {
            "Bucket": self.bucket,
            "Key": self.key,
            "ResponseContentDisposition": f'{disposition}; filename="{self.filename}"',
        }
        return client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )

    def exists_in_storage(self) -> bool:
        """Check if the file actually exists in S3."""
        client = self.get_s3_client()
        try:
            client.head_object(Bucket=self.bucket, Key=self.key)
            return True
        except client.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def delete(self) -> tuple[int, dict[str, int]]:
        """Delete the file from S3 and the database record."""
        client = self.get_s3_client()
        client.delete_object(Bucket=self.bucket, Key=self.key)
        return super().delete()

    @property
    def extension(self) -> str:
        """Get the file extension (lowercase, without dot)."""
        if "." in self.filename:
            return self.filename.rsplit(".", 1)[-1].lower()
        return ""

    @property
    def size_display(self) -> str:
        """Human-readable file size."""
        size = self.byte_size
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

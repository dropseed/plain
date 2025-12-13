from __future__ import annotations

import mimetypes
from datetime import datetime
from uuid import UUID, uuid4

from plain import models
from plain.models import types
from plain.runtime import settings

from . import storage


@models.register_model
class S3File(models.Model):
    """
    Represents a file stored in S3-compatible storage.

    This model stores metadata about files. The actual file content
    is stored in S3. Link to this model using S3FileField() on your models.
    """

    query: models.QuerySet[S3File] = models.QuerySet()

    uuid: UUID = types.UUIDField(default=uuid4)

    # S3 storage location
    key: str = types.CharField(max_length=500)

    # File metadata
    filename: str = types.CharField(max_length=255)
    content_type: str = types.CharField(max_length=100)
    byte_size: int = types.PositiveBigIntegerField()
    checksum: str = types.CharField(max_length=64, required=False)

    # Extensible metadata (dimensions, duration, etc.)
    metadata: dict = types.JSONField(default=dict)

    created_at: datetime = types.DateTimeField(auto_now_add=True)

    model_options = models.Options(
        indexes=[
            models.Index(fields=["uuid"]),
            models.Index(fields=["key"]),
            models.Index(fields=["created_at"]),
        ],
        constraints=[
            models.UniqueConstraint(fields=["uuid"], name="plains3_s3file_unique_uuid"),
        ],
    )

    def __str__(self) -> str:
        return self.filename

    @classmethod
    def generate_key(cls, filename: str) -> str:
        """Generate a unique S3 key for a new file."""
        ext = ""
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower()
        return f"{settings.S3_UPLOAD_KEY_PREFIX}{uuid4()}{ext}"

    @classmethod
    def create_presigned_upload(
        cls,
        *,
        filename: str,
        content_type: str | None = None,
        byte_size: int,
    ) -> dict:
        """
        Create a new S3File record and return presigned upload data.

        The file record is created immediately but the file isn't uploaded yet.
        After the client uploads directly to S3, call verify_upload() to confirm.

        Returns:
            {
                "file_id": UUID,
                "key": str,
                "upload_url": str,
                "upload_fields": dict,
            }
        """
        if content_type is None:
            content_type, _ = mimetypes.guess_type(filename)
            content_type = content_type or "application/octet-stream"

        key = cls.generate_key(filename)

        # Create the file record
        file = cls.query.create(
            key=key,
            filename=filename,
            content_type=content_type,
            byte_size=byte_size,
        )

        # Generate presigned upload URL
        presign = storage.generate_presigned_upload_url(key, content_type)

        return {
            "file_id": str(file.uuid),
            "key": key,
            "upload_url": presign["url"],
            "upload_fields": presign["fields"],
        }

    def download_url(self, *, expires_in: int | None = None) -> str:
        """Generate a presigned URL for downloading this file."""
        return storage.generate_presigned_download_url(
            self.key,
            expires_in=expires_in,
            filename=self.filename,
        )

    def exists_in_storage(self) -> bool:
        """Check if the file actually exists in S3."""
        return storage.head_object(self.key) is not None

    def delete(self) -> None:
        """Delete the file from S3 and the database record."""
        storage.delete_object(self.key)
        super().delete()

    @property
    def extension(self) -> str:
        """Get the file extension (lowercase, without dot)."""
        if "." in self.filename:
            return self.filename.rsplit(".", 1)[-1].lower()
        return ""

    def is_image(self) -> bool:
        """Check if this file is an image based on content type."""
        return self.content_type.startswith("image/")

    def is_video(self) -> bool:
        """Check if this file is a video based on content type."""
        return self.content_type.startswith("video/")

    def is_audio(self) -> bool:
        """Check if this file is audio based on content type."""
        return self.content_type.startswith("audio/")

    def is_pdf(self) -> bool:
        """Check if this file is a PDF."""
        return self.content_type == "application/pdf"

    @property
    def size_display(self) -> str:
        """Human-readable file size."""
        size = self.byte_size
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

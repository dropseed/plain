from __future__ import annotations

from typing import Any

from plain import models
from plain.models.fields.related import ForeignKeyField


class S3FileField(ForeignKeyField):
    """
    A ForeignKey field that links to an S3File with S3 configuration.

    Usage:
        class Document(models.Model):
            file: S3File | None = S3FileField(bucket="my-bucket")

            # With optional configuration:
            avatar: S3File | None = S3FileField(
                bucket="avatars-bucket",
                key_prefix="users/",
                acl="public-read",
            )

    The bucket is required. key_prefix and acl are optional.

    By default, the field is optional (allow_null=True) and uses SET_NULL
    on delete to avoid cascading deletes of your records when files are removed.
    """

    def __init__(
        self,
        bucket: str,
        *,
        key_prefix: str = "",
        acl: str = "",
        on_delete: Any = None,
        **kwargs: Any,
    ):
        # Import here to avoid circular imports
        from .models import S3File

        # Store S3 configuration
        self.bucket = bucket
        self.key_prefix = key_prefix
        self.acl = acl

        # Set FK defaults
        if on_delete is None:
            on_delete = models.SET_NULL
        kwargs.setdefault("allow_null", True)
        kwargs.setdefault("required", False)

        super().__init__(S3File, on_delete=on_delete, **kwargs)

    def upload(self, file):
        """
        Upload a file using this field's configuration.

        Args:
            file: An uploaded file object with name, size, content_type, and read() method

        Returns:
            The created S3File instance
        """
        from .models import S3File

        return S3File.upload(
            bucket=self.bucket,
            file=file,
            key_prefix=self.key_prefix,
            acl=self.acl,
        )

    def create_presigned_upload(
        self,
        *,
        filename: str,
        byte_size: int,
        content_type: str | None = None,
    ) -> dict:
        """
        Create a presigned upload using this field's configuration.

        Returns:
            {
                "file_id": str (UUID),
                "key": str,
                "upload_url": str,
                "upload_fields": dict,
            }
        """
        from .models import S3File

        return S3File.create_presigned_upload(
            bucket=self.bucket,
            filename=filename,
            byte_size=byte_size,
            content_type=content_type,
            key_prefix=self.key_prefix,
            acl=self.acl,
        )

    def formfield(self, **kwargs):
        """Return an S3FileField form field for use in ModelForms."""
        from .forms import S3FileField as S3FileFormField

        defaults = {
            "bucket": self.bucket,
            "key_prefix": self.key_prefix,
            "acl": self.acl,
            "required": not self.allow_null,
        }
        defaults.update(kwargs)
        return S3FileFormField(**defaults)

    def deconstruct(self) -> tuple:
        """Support migrations by including S3 configuration."""
        name, path, args, kwargs = super().deconstruct()
        # Add our custom attributes
        kwargs["bucket"] = self.bucket
        if self.key_prefix:
            kwargs["key_prefix"] = self.key_prefix
        if self.acl:
            kwargs["acl"] = self.acl
        # Remove the 'to' argument since we always point to S3File
        args = ()
        return name, path, args, kwargs

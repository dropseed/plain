from __future__ import annotations

from typing import Any

from plain import models
from plain.models.fields.related import ForeignKeyField

from .models import PresignedUpload


class S3FileField(ForeignKeyField):
    """
    A ForeignKey field that links to an S3File with S3 configuration.

    Usage:
        class Document(models.Model):
            # Uses S3_BUCKET setting:
            file: S3File | None = S3FileField()

            # With optional configuration:
            avatar: S3File | None = S3FileField(
                bucket="avatars-bucket",
                key_prefix="users/",
                acl="public-read",
            )

    By default, the field is optional (allow_null=True) and uses SET_NULL
    on delete to avoid cascading deletes of your records when files are removed.
    """

    def __init__(
        self,
        bucket: str = "",
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

    def upload(self, file: Any) -> Any:
        """
        Upload a file using this field's configuration.

        Returns the created S3File instance.
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
    ) -> PresignedUpload:
        """Create a presigned upload using this field's configuration."""
        from .models import S3File

        return S3File.create_presigned_upload(
            bucket=self.bucket,
            filename=filename,
            byte_size=byte_size,
            content_type=content_type,
            key_prefix=self.key_prefix,
            acl=self.acl,
        )

    def formfield(self, **kwargs: Any) -> Any:
        """Return an S3FileField form field for use in ModelForms."""
        from .forms import S3FileField as S3FileFormField

        return S3FileFormField(
            bucket=self.bucket,
            key_prefix=self.key_prefix,
            acl=self.acl,
            required=kwargs.pop("required", not self.allow_null),
            **kwargs,
        )

    def deconstruct(self) -> tuple:
        """Support migrations by including S3 configuration."""
        name, path, args, kwargs = super().deconstruct()
        # Add our custom attributes
        if self.bucket:
            kwargs["bucket"] = self.bucket
        if self.key_prefix:
            kwargs["key_prefix"] = self.key_prefix
        if self.acl:
            kwargs["acl"] = self.acl
        # Remove the 'to' argument since we always point to S3File
        args = ()
        return name, path, args, kwargs

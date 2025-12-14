from __future__ import annotations

from typing import Any

from plain.forms.fields import FileField


class S3FileField(FileField):
    """
    A form field that uploads files to S3.

    Usage in a form:
        class DocumentForm(Form):
            title = fields.CharField()
            file = S3FileField(bucket="my-bucket")

    The cleaned value is an S3File instance (or None if no file uploaded).
    """

    def __init__(
        self,
        bucket: str,
        *,
        key_prefix: str = "",
        acl: str = "",
        **kwargs,
    ):
        self.bucket = bucket
        self.key_prefix = key_prefix
        self.acl = acl
        super().__init__(**kwargs)

    def clean(self, data: Any, initial: Any = None) -> Any:  # type: ignore[override]
        file = super().clean(data, initial)

        if file is None or file is False:
            return file

        # Upload to S3 and return S3File instance
        from .models import S3File

        return S3File.upload(
            bucket=self.bucket,
            file=file,
            key_prefix=self.key_prefix,
            acl=self.acl,
        )

from __future__ import annotations

from plain import models
from plain.models import types


def S3FileField(**kwargs) -> types.ForeignKeyField:
    """
    A ForeignKey field that links to an S3File.

    Usage:
        class Document(models.Model):
            file: S3File | None = S3FileField()

    By default, the field is optional (allow_null=True) and uses SET_NULL
    on delete to avoid cascading deletes of your records when files are removed.
    """
    # Import here to avoid circular imports
    from .models import S3File

    kwargs.setdefault("on_delete", models.SET_NULL)
    kwargs.setdefault("allow_null", True)
    kwargs.setdefault("required", False)

    return types.ForeignKeyField(S3File, **kwargs)

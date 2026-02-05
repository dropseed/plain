from __future__ import annotations

from datetime import datetime

from plain import models
from plain.models import types
from plain.runtime import SettingsReference

__all__ = ["SupportFormEntry"]


@models.register_model
class SupportFormEntry(models.Model):
    user = types.ForeignKeyField(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=models.SET_NULL,
        allow_null=True,
        required=False,
    )
    name: str = types.CharField(max_length=255)
    email: str = types.EmailField()
    message: str = types.TextField()
    created_at: datetime = types.DateTimeField(auto_now_add=True)
    form_slug: str = types.CharField(max_length=255)
    # referrer? source? session?
    # extra_data

    query: models.QuerySet[SupportFormEntry] = models.QuerySet()

    model_options = models.Options(
        ordering=["-created_at"],
        indexes=[
            models.Index(fields=["created_at"]),
        ],
    )

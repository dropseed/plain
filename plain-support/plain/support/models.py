from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from plain import models
from plain.models import types
from plain.runtime import SettingsReference


@models.register_model
class SupportFormEntry(models.Model):
    user = types.ForeignKey(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=models.SET_NULL,
        related_name="support_form_entries",
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

    query: ClassVar[models.QuerySet[SupportFormEntry]] = models.QuerySet()

    model_options = models.Options(
        ordering=["-created_at"],
        indexes=[
            models.Index(fields=["created_at"]),
        ],
    )

from __future__ import annotations

from datetime import datetime
from typing import Any

from plain import models
from plain.runtime import SettingsReference


@models.register_model
class SupportFormEntry(models.Model):
    user: Any = models.ForeignKey(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=models.SET_NULL,
        related_name="support_form_entries",
        allow_null=True,
        required=False,
    )
    name: str = models.CharField(max_length=255)
    email: str = models.EmailField()
    message: str = models.TextField()
    created_at: datetime = models.DateTimeField(auto_now_add=True)
    form_slug: str = models.CharField(max_length=255)
    # referrer? source? session?
    # extra_data

    model_options = models.Options(
        ordering=["-created_at"],
        indexes=[
            models.Index(fields=["created_at"]),
        ],
    )

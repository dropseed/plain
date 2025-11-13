from __future__ import annotations

from datetime import datetime
from typing import Any

from plain.models import (
    SET_NULL,
    CharField,
    DateTimeField,
    EmailField,
    Field,
    ForeignKey,
    Index,
    Model,
    Options,
    TextField,
    register_model,
)
from plain.runtime import SettingsReference


@register_model
class SupportFormEntry(Model):
    user: Field[Any | None] = ForeignKey(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=SET_NULL,
        related_name="support_form_entries",
        allow_null=True,
    )
    name: Field[str] = CharField(max_length=255)
    email: Field[str] = EmailField()
    message: Field[str] = TextField()
    created_at: Field[datetime] = DateTimeField(auto_now_add=True)
    form_slug: Field[str] = CharField(max_length=255)
    # referrer? source? session?
    # extra_data

    model_options = Options(
        ordering=["-created_at"],
        indexes=[
            Index(fields=["created_at"]),
        ],
    )

from __future__ import annotations

from plain.models import (
    SET_NULL,
    CharField,
    DateTimeField,
    EmailField,
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
    user = ForeignKey(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=SET_NULL,
        related_name="support_form_entries",
        allow_null=True,
    )
    name = CharField(max_length=255)
    email = EmailField()
    message = TextField()
    created_at = DateTimeField(auto_now_add=True)
    form_slug = CharField(max_length=255)
    # referrer? source? session?
    # extra_data

    model_options = Options(
        ordering=["-created_at"],
        indexes=[
            Index(fields=["created_at"]),
        ],
    )

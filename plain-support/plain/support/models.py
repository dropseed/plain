from __future__ import annotations

from datetime import datetime

from plain import postgres
from plain.postgres import types
from plain.runtime import SettingsReference

__all__ = ["SupportFormEntry"]


@postgres.register_model
class SupportFormEntry(postgres.Model):
    user = types.ForeignKeyField(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
    )
    name: str = types.TextField(max_length=255)
    email: str = types.EmailField()
    message: str = types.TextField()
    created_at: datetime = types.DateTimeField(auto_now_add=True)
    form_slug: str = types.TextField(max_length=255)
    # referrer? source? session?
    # extra_data

    query: postgres.QuerySet[SupportFormEntry] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["-created_at"],
        indexes=[
            postgres.Index(fields=["created_at"]),
        ],
    )

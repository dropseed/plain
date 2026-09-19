"""Test fixtures for QuerySet.upsert() and QuerySet.bulk_upsert()."""

from __future__ import annotations

from datetime import datetime

from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class UpsertOwner(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)


@postgres.register_model
class UpsertItem(postgres.Model):
    key: Field[str] = types.TextField(max_length=100)
    value: Field[int] = types.IntegerField(default=0)
    label: Field[str] = types.TextField(default="", required=False)
    owner: Field[UpsertOwner | None] = types.ForeignKeyField(
        UpsertOwner,
        on_delete=postgres.CASCADE,
        allow_null=True,
        required=False,
        default=None,
    )
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(create_now=True, update_now=True)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(fields=["key"], name="upsertitem_key_unique"),
        ]
    )

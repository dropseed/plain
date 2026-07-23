"""Test fixtures for QuerySet.bulk_upsert()."""

from __future__ import annotations

from plain import postgres
from plain.postgres import types


@postgres.register_model
class UpsertOwner(postgres.Model):
    name = types.TextField(max_length=100)

    query: postgres.QuerySet[UpsertOwner] = postgres.QuerySet()


@postgres.register_model
class UpsertItem(postgres.Model):
    key = types.TextField(max_length=100)
    value = types.IntegerField(default=0)
    label = types.TextField(default="", required=False)
    owner = types.ForeignKeyField(
        UpsertOwner, on_delete=postgres.CASCADE, allow_null=True, required=False
    )

    query: postgres.QuerySet[UpsertItem] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(fields=["key"], name="upsertitem_key_unique"),
        ]
    )

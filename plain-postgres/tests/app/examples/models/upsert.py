"""Test fixtures for QuerySet.upsert() and QuerySet.bulk_upsert()."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

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

    @property
    def label_upper(self) -> str:
        """A settable property, to pin that upsert() refuses to write one."""
        return self.label.upper()

    @label_upper.setter
    def label_upper(self, value: str) -> None:
        self.label = value.lower()


# NOTE: #86 grows an equivalent UpsertTenant/UpsertScoped pair; collapse onto
# whichever survives the merge.
@postgres.register_model
class UpsertScope(postgres.Model):
    """Parent for the composite (foreign key, key) conflict target."""

    name: Field[str] = types.TextField(max_length=100)

    entries: ClassVar[types.ReverseForeignKey[UpsertScopedItem]] = (
        types.ReverseForeignKey(to="UpsertScopedItem", field="scope")
    )


@postgres.register_model
class UpsertScopedItem(postgres.Model):
    scope: Field[UpsertScope] = types.ForeignKeyField(
        UpsertScope, on_delete=postgres.CASCADE
    )
    key: Field[str] = types.TextField(max_length=100)
    value: Field[int] = types.IntegerField(default=0)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["scope", "key"], name="upsertscopeditem_scope_key_unique"
            ),
        ]
    )

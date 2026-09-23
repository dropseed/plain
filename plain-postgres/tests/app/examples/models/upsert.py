"""Test fixtures for QuerySet.upsert() and QuerySet.bulk_upsert()."""

from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from zoneinfo import ZoneInfo

from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class UpsertItem(postgres.Model):
    key: Field[str] = types.TextField(max_length=100)
    value: Field[int] = types.IntegerField(default=0)
    label: Field[str] = types.TextField(default="", required=False)

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


@postgres.register_model
class UpsertPair(postgres.Model):
    """Composite conflict key -- unique on (bucket, slug), not on either alone."""

    bucket: Field[str] = types.TextField(max_length=100)
    slug: Field[str] = types.TextField(max_length=100)
    value: Field[int] = types.IntegerField(default=0)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["bucket", "slug"], name="upsertpair_bucket_slug_unique"
            ),
        ]
    )


@postgres.register_model
class UpsertTenant(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)

    scoped: ClassVar[types.ReverseForeignKey[UpsertScoped]] = types.ReverseForeignKey(
        to="UpsertScoped", field="tenant"
    )


@postgres.register_model
class UpsertScoped(postgres.Model):
    """A foreign key as part of the conflict key, and as an updated column."""

    tenant: Field[UpsertTenant] = types.ForeignKeyField(
        UpsertTenant, on_delete=postgres.CASCADE
    )
    slug: Field[str] = types.TextField(max_length=100)
    value: Field[int] = types.IntegerField(default=0)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["tenant", "slug"], name="upsertscoped_tenant_slug_unique"
            ),
        ]
    )


@postgres.register_model
class UpsertValueKey(postgres.Model):
    """A composite conflict key of column types whose Python values are
    unhashable (jsonb dicts), unorderable (ZoneInfo), or neither (memoryview).
    """

    payload: Field[object] = types.JSONField()
    blob: Field[bytes | memoryview] = types.BinaryField()
    zone: Field[ZoneInfo] = types.TimeZoneField()
    value: Field[int] = types.IntegerField(default=0)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["payload", "blob", "zone"],
                name="upsertvaluekey_payload_blob_zone_unique",
            ),
        ]
    )


@postgres.register_model
class UpsertFloatKey(postgres.Model):
    """A float conflict key -- the column type that can hold NaN."""

    score: Field[float] = types.FloatField()
    value: Field[int] = types.IntegerField(default=0)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["score"], name="upsertfloatkey_score_unique"
            ),
        ]
    )


@postgres.register_model
class UpsertDecimalKey(postgres.Model):
    """A numeric conflict key -- the column type whose scale Python keeps and
    Postgres does not."""

    amount: Field[Decimal] = types.DecimalField(max_digits=12, decimal_places=4)
    value: Field[int] = types.IntegerField(default=0)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["amount"], name="upsertdecimalkey_amount_unique"
            ),
        ]
    )


@postgres.register_model
class UpsertStamped(postgres.Model):
    """Timestamp columns nobody names: update_now has to be refreshed by the
    conflict update, create_now has to be left alone. Also carries a foreign
    key that is *not* part of the conflict key, which is the only place a
    related instance can be a conflict_defaults value.
    """

    key: Field[str] = types.TextField(max_length=100)
    value: Field[int] = types.IntegerField(default=0)
    tenant: Field[UpsertTenant | None] = types.ForeignKeyField(
        UpsertTenant,
        on_delete=postgres.CASCADE,
        allow_null=True,
        required=False,
        default=None,
    )
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(create_now=True, update_now=True)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(fields=["key"], name="upsertstamped_key_unique"),
        ]
    )

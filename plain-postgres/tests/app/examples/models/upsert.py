"""Test fixtures for QuerySet.bulk_upsert()."""

from __future__ import annotations

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

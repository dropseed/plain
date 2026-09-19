"""Test fixtures for QuerySet.bulk_upsert()."""

from __future__ import annotations

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

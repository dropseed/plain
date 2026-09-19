"""`bulk_create()` inserts and `bulk_upsert()` insert-or-updates.

Both hand back the model instances they were given. `bulk_upsert()` takes field
references for its conflict target and its update columns -- including a
`Model.fk` reference, which types as the related model class rather than a
Field -- and `bulk_create()` no longer takes a conflict surface at all.
"""

from __future__ import annotations

from typing import assert_type

from app.examples.models.upsert import UpsertItem, UpsertScoped, UpsertTenant


def must_accept_bulk_create_as_instances() -> None:
    assert_type(
        UpsertItem.query.bulk_create([UpsertItem(key="a", value=1)]),
        list[UpsertItem],
    )


def must_accept_bulk_upsert_as_instances() -> None:
    assert_type(
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1)],
            update_fields=[UpsertItem.value],
            unique_fields=[UpsertItem.key],
        ),
        list[UpsertItem],
    )


def must_reject_string_field_names() -> None:
    # Runtime half:
    # tests/public/test_bulk_upsert.py::test_bulk_upsert_string_field_rejected.
    UpsertItem.query.bulk_upsert(
        [UpsertItem(key="a", value=1)],
        update_fields=["value"],  # ty: ignore[invalid-argument-type]
        unique_fields=[UpsertItem.key],
    )


def must_reject_bulk_create_conflict_kwargs() -> None:
    # bulk_create is insert-only. Runtime half: tests/public/test_bulk_upsert.py
    # ::test_bulk_create_no_longer_accepts_update_conflicts.
    UpsertItem.query.bulk_create(
        [UpsertItem(key="a", value=1)],
        update_conflicts=True,  # ty: ignore[unknown-argument]
    )


def must_accept_a_foreign_key_reference() -> None:
    # Model.fk types as the related model class, not a Field, so the element
    # type of these lists is the union. Runtime half:
    # tests/public/test_bulk_upsert.py
    # ::test_bulk_upsert_foreign_key_in_unique_fields.
    UpsertScoped.query.bulk_upsert(
        [UpsertScoped(tenant=UpsertTenant(name="t"), slug="s", value=1)],
        update_fields=[UpsertScoped.value],
        unique_fields=[UpsertScoped.tenant, UpsertScoped.slug],
    )

"""QuerySet.bulk_upsert() inserts new rows and updates conflicting ones.

One INSERT ... ON CONFLICT (unique_fields) DO UPDATE ... RETURNING per batch.
Every returned object -- inserted or updated -- comes back with its DB-returned
fields (primary key, DB defaults) populated, matched to its row by unique key.
"""

from __future__ import annotations

import pytest
from app.examples.models.defaults import DBDefaultsExample
from app.examples.models.mixins import MixinTestModel
from app.examples.models.returning import ReturningEvent
from app.examples.models.upsert import (
    UpsertItem,
    UpsertPair,
    UpsertScoped,
    UpsertTenant,
)
from plain.postgres.exceptions import FieldError


def test_bulk_upsert_inserts_new_rows_and_sets_pks(db):
    items = [
        UpsertItem(key="a", value=1),
        UpsertItem(key="b", value=2),
    ]
    returned = UpsertItem.query.bulk_upsert(
        items, update_fields=[UpsertItem.value], unique_fields=[UpsertItem.key]
    )

    assert [r.id for r in returned] == [item.id for item in items]
    assert all(item.id is not None for item in items)
    stored = {row.key: row.value for row in UpsertItem.query.all()}
    assert stored == {"a": 1, "b": 2}


def test_bulk_upsert_mixed_batch_inserts_and_updates(db):
    UpsertItem(key="a", value=1).create()
    existing_id = UpsertItem.query.get(key="a").id

    items = [
        UpsertItem(key="a", value=10),  # conflicts -> update
        UpsertItem(key="b", value=20),  # new -> insert
    ]
    UpsertItem.query.bulk_upsert(
        items, update_fields=[UpsertItem.value], unique_fields=[UpsertItem.key]
    )

    by_key = {item.key: item for item in items}
    # The updated row keeps its original primary key.
    assert by_key["a"].id == existing_id
    assert by_key["b"].id is not None
    assert by_key["b"].id != existing_id

    stored = {row.key: row.value for row in UpsertItem.query.all()}
    assert stored == {"a": 10, "b": 20}


def test_bulk_upsert_updates_only_named_fields(db):
    UpsertItem(key="a", value=1, label="original").create()

    UpsertItem.query.bulk_upsert(
        [UpsertItem(key="a", value=99, label="ignored")],
        update_fields=[UpsertItem.value],
        unique_fields=[UpsertItem.key],
    )

    row = UpsertItem.query.get(key="a")
    assert row.value == 99  # named field updated
    assert row.label == "original"  # field not in update_fields preserved


def test_bulk_upsert_matches_returned_rows_by_key_not_order(db):
    # Seed so every input row conflicts; RETURNING order under ON CONFLICT is
    # not guaranteed to match VALUES order, so each object must be matched to
    # its own row by unique key.
    for key in ("a", "b", "c"):
        UpsertItem(key=key, value=0).create()
    seeded_ids = {row.key: row.id for row in UpsertItem.query.all()}

    items = [
        UpsertItem(key="c", value=3),
        UpsertItem(key="a", value=1),
        UpsertItem(key="b", value=2),
    ]
    returned = UpsertItem.query.bulk_upsert(
        items, update_fields=[UpsertItem.value], unique_fields=[UpsertItem.key]
    )

    # Batches are issued in conflict-key order, but the caller gets its own
    # order back.
    assert [r.key for r in returned] == ["c", "a", "b"]

    for item in items:
        assert item.id == seeded_ids[item.key]

    stored = {row.key: row.value for row in UpsertItem.query.all()}
    assert stored == {"a": 1, "b": 2, "c": 3}


def test_bulk_upsert_empty_returns_empty(db):
    assert (
        UpsertItem.query.bulk_upsert(
            [], update_fields=[UpsertItem.value], unique_fields=[UpsertItem.key]
        )
        == []
    )


def test_bulk_upsert_batches(db):
    items = [UpsertItem(key=f"k{i}", value=i) for i in range(5)]
    UpsertItem.query.bulk_upsert(
        items,
        update_fields=[UpsertItem.value],
        unique_fields=[UpsertItem.key],
        batch_size=2,
    )

    assert all(item.id is not None for item in items)
    assert UpsertItem.query.count() == 5


def test_bulk_upsert_unique_fields_must_match_a_constraint(db):
    with pytest.raises(ValueError, match="must name the primary key"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1)],
            update_fields=[UpsertItem.value],
            unique_fields=[UpsertItem.value],  # no unique constraint on value
        )


def test_bulk_upsert_null_unique_value_rejected(db):
    with pytest.raises(ValueError, match="non-null key"):
        UpsertItem.query.bulk_upsert(
            # A null unique value is a type error the checker catches; the
            # runtime guard is what protects callers that aren't type-checked.
            [UpsertItem(key=None, value=1)],  # ty: ignore[invalid-argument-type]
            update_fields=[UpsertItem.value],
            unique_fields=[UpsertItem.key],
        )


def test_bulk_upsert_update_fields_cannot_overlap_unique_fields(db):
    with pytest.raises(ValueError, match="cannot overlap unique_fields"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1)],
            update_fields=[UpsertItem.key],
            unique_fields=[UpsertItem.key],
        )


def test_bulk_upsert_requires_update_fields(db):
    with pytest.raises(ValueError, match="requires update_fields"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1)],
            update_fields=[],
            unique_fields=[UpsertItem.key],
        )


def test_bulk_upsert_string_field_rejected(db):
    with pytest.raises(TypeError, match="takes field references, not strings"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1)],
            update_fields=["value"],  # ty: ignore[invalid-argument-type]
            unique_fields=[UpsertItem.key],
        )


def test_bulk_upsert_wrong_model_field_rejected(db):
    with pytest.raises(FieldError, match="belongs to a different model"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1)],
            update_fields=[UpsertItem.value],
            unique_fields=[ReturningEvent.label],
        )


def test_bulk_create_no_longer_accepts_update_conflicts(db):
    # bulk_create is insert-only now; the conflict surface moved to bulk_upsert.
    removed_conflict_kwargs: dict[str, object] = {
        "update_conflicts": True,
        "update_fields": ["value"],
        "unique_fields": ["key"],
    }
    with pytest.raises(TypeError):
        UpsertItem.query.bulk_create(
            [UpsertItem(key="a", value=1)],
            **removed_conflict_kwargs,  # ty: ignore[invalid-argument-type]
        )


def test_bulk_upsert_composite_unique_fields(db):
    UpsertPair(bucket="b1", slug="s1", value=1).create()
    seeded_id = UpsertPair.query.get(bucket="b1", slug="s1").id

    items = [
        UpsertPair(bucket="b1", slug="s1", value=10),  # conflicts -> update
        UpsertPair(bucket="b1", slug="s2", value=20),  # same bucket, new slug
        UpsertPair(bucket="b2", slug="s1", value=30),  # same slug, new bucket
    ]
    UpsertPair.query.bulk_upsert(
        items,
        update_fields=[UpsertPair.value],
        unique_fields=[UpsertPair.bucket, UpsertPair.slug],
    )

    # The conflicting row is matched back by the whole composite key.
    assert items[0].id == seeded_id
    assert len({item.id for item in items}) == 3

    stored = {(row.bucket, row.slug): row.value for row in UpsertPair.query.all()}
    assert stored == {("b1", "s1"): 10, ("b1", "s2"): 20, ("b2", "s1"): 30}


def test_bulk_upsert_duplicate_keys_rejected(db):
    # Postgres raises a cardinality violation if one statement touches a row
    # twice, and splitting duplicates across batches would silently let the
    # last one win -- so they are refused up front, whatever the batch size.
    with pytest.raises(ValueError, match="more than one UpsertItem"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1), UpsertItem(key="a", value=2)],
            update_fields=[UpsertItem.value],
            unique_fields=[UpsertItem.key],
            batch_size=1,
        )

    assert UpsertItem.query.count() == 0


def test_bulk_upsert_database_generated_unique_field_rejected(db):
    # db_uuid is generate=True, so the objects hold a DatabaseDefault sentinel
    # rather than a value to conflict on.
    with pytest.raises(ValueError, match="the database generates its value"):
        DBDefaultsExample.query.bulk_upsert(
            [DBDefaultsExample(name="a")],
            update_fields=[DBDefaultsExample.name],
            unique_fields=[DBDefaultsExample.db_uuid],
        )


def test_bulk_upsert_validates_arguments_even_when_empty(db):
    # An empty objs list is still a bad call if the fields are wrong.
    with pytest.raises(TypeError, match="takes field references, not strings"):
        UpsertItem.query.bulk_upsert(
            [],
            update_fields=["value"],  # ty: ignore[invalid-argument-type]
            unique_fields=[UpsertItem.key],
        )


def test_bulk_upsert_refreshes_update_now_columns_without_naming_them(db):
    MixinTestModel(name="a").create()
    seeded = MixinTestModel.query.get(name="a")

    renamed = MixinTestModel(name="b")
    renamed.id = seeded.id
    MixinTestModel.query.bulk_upsert(
        [renamed],
        update_fields=[MixinTestModel.name],  # updated_at deliberately absent
        unique_fields=[MixinTestModel.id],
    )

    row = MixinTestModel.query.get(id=seeded.id)
    assert row.name == "b"
    # The row was updated, so its update_now column was too.
    assert row.updated_at > seeded.updated_at
    # And the object handed back agrees with the row it was hydrated from --
    # pre_save stamps the object, EXCLUDED carries that same stamp to the row.
    assert renamed.updated_at == row.updated_at


def test_bulk_upsert_cannot_update_a_database_generated_column(db):
    # created_at is create_now-only: EXCLUDED would carry a fresh now() and
    # reset the creation timestamp on every update.
    with pytest.raises(ValueError, match="the database generates its value"):
        MixinTestModel.query.bulk_upsert(
            [MixinTestModel(name="a")],
            update_fields=[MixinTestModel.created_at],
            unique_fields=[MixinTestModel.id],
        )


def test_bulk_upsert_update_now_unique_field_rejected(db):
    with pytest.raises(ValueError, match="stamped again on every write"):
        MixinTestModel.query.bulk_upsert(
            [MixinTestModel(name="a")],
            update_fields=[MixinTestModel.name],
            unique_fields=[MixinTestModel.updated_at],
        )


def test_bulk_upsert_foreign_key_in_unique_fields(db):
    # Model.fk is a relation descriptor, not a Field, but it is the only way to
    # name the foreign key column -- so the write-API field lists accept it.
    tenant = UpsertTenant(name="t1")
    tenant.create()
    tenant = UpsertTenant.query.get(name="t1")
    UpsertScoped(tenant=tenant, slug="a", value=1).create()
    seeded_id = UpsertScoped.query.get(slug="a").id

    items = [
        UpsertScoped(tenant=tenant, slug="a", value=10),  # conflicts -> update
        UpsertScoped(tenant=tenant, slug="b", value=20),  # new -> insert
    ]
    UpsertScoped.query.bulk_upsert(
        items,
        update_fields=[UpsertScoped.value],
        unique_fields=[UpsertScoped.tenant, UpsertScoped.slug],
    )

    assert items[0].id == seeded_id
    assert items[1].id != seeded_id
    stored = {row.slug: row.value for row in UpsertScoped.query.all()}
    assert stored == {"a": 10, "b": 20}


def test_bulk_upsert_foreign_key_in_update_fields(db):
    first = UpsertTenant(name="t1")
    first.create()
    second = UpsertTenant(name="t2")
    second.create()
    first = UpsertTenant.query.get(name="t1")
    second = UpsertTenant.query.get(name="t2")

    UpsertScoped(tenant=first, slug="a", value=1).create()
    seeded_id = UpsertScoped.query.get(slug="a").id

    moved = UpsertScoped(tenant=second, slug="a", value=2)
    moved.id = seeded_id
    UpsertScoped.query.bulk_upsert(
        [moved],
        update_fields=[UpsertScoped.tenant, UpsertScoped.value],
        unique_fields=[UpsertScoped.id],
    )

    row = UpsertScoped.query.get(id=seeded_id)
    assert row.tenant.id == second.id
    assert row.value == 2

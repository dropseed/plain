"""QuerySet.bulk_upsert() inserts new rows and updates conflicting ones.

One INSERT ... ON CONFLICT (unique_fields) DO UPDATE ... RETURNING per batch.
Every returned object -- inserted or updated -- comes back with its DB-returned
fields (primary key, DB defaults) populated, matched to its row by unique key.
"""

from __future__ import annotations

import pytest
from app.examples.models.upsert import UpsertItem


def test_bulk_upsert_inserts_new_rows_and_sets_pks(db):
    items = [
        UpsertItem(key="a", value=1),
        UpsertItem(key="b", value=2),
    ]
    returned = UpsertItem.query.bulk_upsert(
        items, update_fields=["value"], unique_fields=["key"]
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
    UpsertItem.query.bulk_upsert(items, update_fields=["value"], unique_fields=["key"])

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
        update_fields=["value"],
        unique_fields=["key"],
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
    UpsertItem.query.bulk_upsert(items, update_fields=["value"], unique_fields=["key"])

    for item in items:
        assert item.id == seeded_ids[item.key]

    stored = {row.key: row.value for row in UpsertItem.query.all()}
    assert stored == {"a": 1, "b": 2, "c": 3}


def test_bulk_upsert_empty_returns_empty(db):
    assert (
        UpsertItem.query.bulk_upsert([], update_fields=["value"], unique_fields=["key"])
        == []
    )


def test_bulk_upsert_batches(db):
    items = [UpsertItem(key=f"k{i}", value=i) for i in range(5)]
    UpsertItem.query.bulk_upsert(
        items, update_fields=["value"], unique_fields=["key"], batch_size=2
    )

    assert all(item.id is not None for item in items)
    assert UpsertItem.query.count() == 5


def test_bulk_upsert_unique_fields_must_match_a_constraint(db):
    with pytest.raises(ValueError, match="must name the primary key"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1)],
            update_fields=["value"],
            unique_fields=["value"],  # no unique constraint on value
        )


def test_bulk_upsert_null_unique_value_rejected(db):
    with pytest.raises(ValueError, match="non-null key"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key=None, value=1)],
            update_fields=["value"],
            unique_fields=["key"],
        )


def test_bulk_upsert_update_fields_cannot_overlap_unique_fields(db):
    with pytest.raises(ValueError, match="cannot overlap unique_fields"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1)],
            update_fields=["key"],
            unique_fields=["key"],
        )


def test_bulk_upsert_requires_update_fields(db):
    with pytest.raises(ValueError, match="requires update_fields"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1)],
            update_fields=[],
            unique_fields=["key"],
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

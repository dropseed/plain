"""QuerySet.upsert() inserts a row or updates the conflicting one.

One INSERT ... ON CONFLICT (unique_fields) DO UPDATE ... RETURNING statement.
Returns (obj, created): obj is hydrated from the post-write row -- no second
query -- and created is True on insert, False on conflict-update.
"""

from __future__ import annotations

import pytest
from app.examples.models.relationships import Widget
from app.examples.models.upsert import UpsertItem, UpsertOwner

from plain.postgres.exceptions import FieldError
from plain.postgres.expressions import F


def test_upsert_inserts_new_row(db):
    obj, created = UpsertItem.query.upsert(key="a", value=1, unique_fields=["key"])

    assert created is True
    assert obj.id is not None
    assert obj.key == "a"
    assert obj.value == 1
    assert UpsertItem.query.get(key="a").value == 1


def test_upsert_updates_conflicting_row(db):
    UpsertItem(key="a", value=1).create()
    existing_id = UpsertItem.query.get(key="a").id

    obj, created = UpsertItem.query.upsert(key="a", value=99, unique_fields=["key"])

    assert created is False
    # The updated row keeps its primary key, and obj carries the merged value.
    assert obj.id == existing_id
    assert obj.value == 99
    assert UpsertItem.query.count() == 1
    assert UpsertItem.query.get(key="a").value == 99


def test_upsert_defaults_apply_on_insert_and_update(db):
    obj, created = UpsertItem.query.upsert(
        key="a", defaults={"value": 5}, unique_fields=["key"]
    )
    assert (created, obj.value) == (True, 5)

    obj, created = UpsertItem.query.upsert(
        key="a", defaults={"value": 7}, unique_fields=["key"]
    )
    assert (created, obj.value) == (False, 7)


def test_upsert_create_defaults_apply_on_insert_only(db):
    obj, created = UpsertItem.query.upsert(
        key="a",
        defaults={"value": 1},
        create_defaults={"label": "created"},
        unique_fields=["key"],
    )
    assert (created, obj.label) == (True, "created")

    # On conflict, create_defaults is not applied, so the label is untouched
    # while defaults still updates value.
    obj, created = UpsertItem.query.upsert(
        key="a",
        defaults={"value": 2},
        create_defaults={"label": "ignored-on-conflict"},
        unique_fields=["key"],
    )
    assert created is False
    assert obj.label == "created"
    assert obj.value == 2


def test_upsert_conflict_defaults_increment_counter_atomically(db):
    UpsertItem(key="a", value=10).create()

    obj, created = UpsertItem.query.upsert(
        key="a",
        value=0,  # the value the INSERT would have proposed (ignored on conflict)
        conflict_defaults={"value": F("value") + 1},
        unique_fields=["key"],
    )

    assert created is False
    assert obj.value == 11
    assert UpsertItem.query.get(key="a").value == 11


def test_upsert_conflict_defaults_apply_on_insert_uses_inserted_value(db):
    # On insert there's no existing row, so the inserted value stands; the
    # conflict_defaults override only takes effect on a later conflict.
    obj, created = UpsertItem.query.upsert(
        key="a",
        value=3,
        conflict_defaults={"value": F("value") + 100},
        unique_fields=["key"],
    )
    assert (created, obj.value) == (True, 3)


def test_upsert_all_unique_fields_is_idempotent(db):
    # When every inserted column is a unique field there's nothing to update;
    # the second call must still return the existing row (created=False).
    obj1, created1 = Widget.query.upsert(
        name="Toyota", size="Tundra", unique_fields=["name", "size"]
    )
    obj2, created2 = Widget.query.upsert(
        name="Toyota", size="Tundra", unique_fields=["name", "size"]
    )

    assert created1 is True
    assert created2 is False
    assert obj1.id == obj2.id
    assert Widget.query.count() == 1


def test_upsert_requires_unique_fields(db):
    with pytest.raises(ValueError, match="requires unique_fields"):
        UpsertItem.query.upsert(key="a", unique_fields=[])


def test_upsert_unique_fields_must_match_a_constraint(db):
    with pytest.raises(ValueError, match="must name the primary key"):
        UpsertItem.query.upsert(key="a", value=1, unique_fields=["value"])


def test_upsert_rejects_null_unique_value(db):
    with pytest.raises(ValueError, match="non-null"):
        UpsertItem.query.upsert(key=None, unique_fields=["key"])


def test_upsert_conflict_defaults_accepts_related_instance(db):
    # A model instance as a conflict_defaults value exercises the related-field
    # branch of assignment-value compilation (prepare_database_save).
    owner = UpsertOwner(name="owner").create()
    UpsertItem(key="a", value=1).create()

    obj, created = UpsertItem.query.upsert(
        key="a",
        value=2,
        conflict_defaults={"owner": owner},
        unique_fields=["key"],
    )

    assert created is False
    assert obj.owner is not None
    assert obj.owner.id == owner.id
    reloaded = UpsertItem.query.get(key="a")
    assert reloaded.owner is not None
    assert reloaded.owner.id == owner.id


def test_upsert_rejects_unknown_field_name(db):
    with pytest.raises(FieldError, match="typo_field"):
        UpsertItem.query.upsert(
            key="a", defaults={"typo_field": 1}, unique_fields=["key"]
        )


def test_upsert_insert_is_one_statement(db, capture_queries):
    with capture_queries() as queries:
        UpsertItem.query.upsert(key="a", value=1, unique_fields=["key"])

    assert len(queries) == 1


def test_upsert_conflict_is_one_statement(db, capture_queries):
    UpsertItem(key="a", value=1).create()

    with capture_queries() as queries:
        UpsertItem.query.upsert(key="a", value=2, unique_fields=["key"])

    assert len(queries) == 1

"""QuerySet.bulk_upsert() inserts new rows and updates conflicting ones.

One INSERT ... ON CONFLICT (unique_fields) DO UPDATE ... RETURNING per batch.
Every returned object -- inserted or updated -- comes back with its DB-returned
fields (primary key, DB defaults) populated from the row at its own position.
"""

from __future__ import annotations

import random
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from app.examples.models.defaults import DBDefaultsExample
from app.examples.models.mixins import MixinTestModel
from app.examples.models.returning import ReturningEvent
from app.examples.models.upsert import (
    UpsertDecimalKey,
    UpsertFloatKey,
    UpsertItem,
    UpsertPair,
    UpsertScoped,
    UpsertTenant,
    UpsertValueKey,
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


def test_bulk_upsert_hydrates_every_object_when_all_of_them_conflict(db):
    # Seed so every input row takes the DO UPDATE path, and pass them out of
    # key order so the deadlock sort actually reorders the batch.
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


def test_bulk_upsert_duplicate_keys_in_one_batch_rejected(db):
    # Postgres refuses to touch a row twice in one statement. The raw
    # CardinalityViolation is re-raised as something that names the problem.
    # It aborts the surrounding transaction, so nothing is queried after it.
    with pytest.raises(ValueError, match=r"same \['key'\] in one statement"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1), UpsertItem(key="a", value=2)],
            update_fields=[UpsertItem.value],
            unique_fields=[UpsertItem.key],
        )


def test_bulk_upsert_duplicate_keys_in_separate_batches_are_legal(db):
    # Split across statements there is no cardinality violation: the first
    # inserts the row and the second updates it.
    items = [UpsertItem(key="a", value=1), UpsertItem(key="a", value=2)]
    UpsertItem.query.bulk_upsert(
        items,
        update_fields=[UpsertItem.value],
        unique_fields=[UpsertItem.key],
        batch_size=1,
    )

    assert UpsertItem.query.count() == 1
    row = UpsertItem.query.get(key="a")
    # Both objects are hydrated, from their own returned row -- the same row.
    assert [item.id for item in items] == [row.id, row.id]
    # Equal keys keep their input order, so the later write is the one that lands.
    assert row.value == 2


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


def test_bulk_upsert_keys_that_python_cannot_sort(db):
    # ZoneInfo and memoryview have no ordering at all and a jsonb dict has no
    # useful one -- the batch still has to be put in a deterministic order.
    chicago = ZoneInfo("America/Chicago")
    utc = ZoneInfo("UTC")
    UpsertValueKey(payload={"a": 1}, blob=b"x", zone=utc, value=1).create()
    seeded_id = UpsertValueKey.query.get(value=1).id

    items = [
        # Conflicts: same key, written with its dict keys in the other order.
        UpsertValueKey(payload={"a": 1}, blob=b"x", zone=utc, value=10),
        UpsertValueKey(payload={"b": 2, "a": 1}, blob=b"y", zone=chicago, value=20),
        UpsertValueKey(payload={"a": 1, "b": 2}, blob=b"z", zone=chicago, value=30),
    ]
    UpsertValueKey.query.bulk_upsert(
        items,
        update_fields=[UpsertValueKey.value],
        unique_fields=[
            UpsertValueKey.payload,
            UpsertValueKey.blob,
            UpsertValueKey.zone,
        ],
    )

    assert items[0].id == seeded_id
    assert len({item.id for item in items}) == 3
    stored = {row.value for row in UpsertValueKey.query.all()}
    assert stored == {10, 20, 30}


def test_bulk_upsert_key_values_that_do_not_compare_to_each_other(db):
    # A jsonb conflict key can hold an object in one row and a number in the
    # next. Those don't compare, and the batches still have to be ordered.
    utc = ZoneInfo("UTC")
    items = [
        UpsertValueKey(payload={"a": 1}, blob=b"x", zone=utc, value=1),
        UpsertValueKey(payload=7, blob=b"x", zone=utc, value=2),
        UpsertValueKey(payload="s", blob=b"x", zone=utc, value=3),
        UpsertValueKey(payload=[1, 2], blob=b"x", zone=utc, value=4),
    ]
    UpsertValueKey.query.bulk_upsert(
        items,
        update_fields=[UpsertValueKey.value],
        unique_fields=[
            UpsertValueKey.payload,
            UpsertValueKey.blob,
            UpsertValueKey.zone,
        ],
    )

    assert len({item.id for item in items}) == 4
    assert {row.value for row in UpsertValueKey.query.all()} == {1, 2, 3, 4}


def test_bulk_upsert_json_key_with_non_string_object_keys(db):
    # jsonb object keys are always strings -- the encoder stringifies an int
    # key on the way in. The sort key has to be canonicalized the same way, or
    # sorting the object's keys compares an int against a str and raises.
    utc = ZoneInfo("UTC")
    UpsertValueKey(
        payload={1: "a", "2": "b", "nested": {"z": 1, "y": 2}},
        blob=b"x",
        zone=utc,
        value=1,
    ).create()
    seeded_id = UpsertValueKey.query.get(value=1).id

    # The same logical key, written with its keys in another order and the
    # int key spelled as a string.
    conflicting = UpsertValueKey(
        payload={"nested": {"y": 2, "z": 1}, "2": "b", "1": "a"},
        blob=b"x",
        zone=utc,
        value=99,
    )
    UpsertValueKey.query.bulk_upsert(
        [conflicting],
        update_fields=[UpsertValueKey.value],
        unique_fields=[
            UpsertValueKey.payload,
            UpsertValueKey.blob,
            UpsertValueKey.zone,
        ],
    )

    assert conflicting.id == seeded_id
    assert UpsertValueKey.query.count() == 1
    assert UpsertValueKey.query.get(id=seeded_id).value == 99


def test_bulk_upsert_nan_key_round_trips(db):
    # Postgres holds NaN equal to NaN for uniqueness, so a NaN key really does
    # conflict -- and sorting it must not raise the way `<` on a NaN would.
    items = [UpsertFloatKey(score=float("nan"), value=1)]
    UpsertFloatKey.query.bulk_upsert(
        items,
        update_fields=[UpsertFloatKey.value],
        unique_fields=[UpsertFloatKey.score],
    )
    seeded_id = items[0].id
    assert seeded_id is not None

    updated = [UpsertFloatKey(score=float("nan"), value=2)]
    UpsertFloatKey.query.bulk_upsert(
        updated,
        update_fields=[UpsertFloatKey.value],
        unique_fields=[UpsertFloatKey.score],
    )

    assert updated[0].id == seeded_id
    assert UpsertFloatKey.query.count() == 1
    assert UpsertFloatKey.query.get(id=seeded_id).value == 2


def test_bulk_upsert_duplicate_nan_keys_in_one_batch_rejected(db):
    # Postgres holds the two NaNs equal, so this is the same row twice.
    with pytest.raises(ValueError, match=r"same \['score'\] in one statement"):
        UpsertFloatKey.query.bulk_upsert(
            [
                UpsertFloatKey(score=float("nan"), value=1),
                UpsertFloatKey(score=float("nan"), value=2),
            ],
            update_fields=[UpsertFloatKey.value],
            unique_fields=[UpsertFloatKey.score],
        )


def test_bulk_upsert_accepts_any_sequence_of_field_references(db):
    # The parameters are Sequence, so a tuple -- or a conflict target hoisted
    # into a variable, which a list parameter would reject as invariant --
    # works as well as an inline list.
    conflict_target = (UpsertPair.bucket, UpsertPair.slug)
    items = [UpsertPair(bucket="b", slug="s", value=1)]
    UpsertPair.query.bulk_upsert(
        items,
        update_fields=(UpsertPair.value,),
        unique_fields=conflict_target,
    )

    assert items[0].id is not None
    assert UpsertPair.query.get(bucket="b", slug="s").value == 1


def test_bulk_upsert_honors_an_id_the_caller_set(db):
    # An explicitly set id is the caller's choice, not ours to discard for a
    # generated one -- bulk_create() honors it, and so does this.
    item = UpsertItem(key="a", value=1)
    item.id = 5
    UpsertItem.query.bulk_upsert(
        [item], update_fields=[UpsertItem.value], unique_fields=[UpsertItem.key]
    )

    assert item.id == 5
    assert UpsertItem.query.get(key="a").id == 5


def test_bulk_upsert_mixes_objects_with_and_without_ids(db):
    # The two go out as separate statements; both still come back hydrated
    # from their own row.
    with_id = UpsertItem(key="a", value=1)
    with_id.id = 5
    without_id = UpsertItem(key="b", value=2)
    UpsertItem.query.bulk_upsert(
        [with_id, without_id],
        update_fields=[UpsertItem.value],
        unique_fields=[UpsertItem.key],
    )

    assert with_id.id == 5
    assert without_id.id is not None
    assert without_id.id != 5
    assert {row.key: row.id for row in UpsertItem.query.all()} == {
        "a": 5,
        "b": without_id.id,
    }


def test_bulk_upsert_across_several_batches_out_of_key_order(db):
    # Every other key already exists, the input is shuffled, and the batches
    # are smaller than the input -- so inserts and updates interleave across
    # statements and the sort reorders them. Each object still has to come
    # back hydrated from its own row.
    for index in range(0, 8, 2):
        UpsertItem(key=f"k{index}", value=0).create()
    seeded = {row.key: row.id for row in UpsertItem.query.all()}

    keys = [f"k{index}" for index in range(8)]
    random.Random(0).shuffle(keys)
    items = [UpsertItem(key=key, value=int(key[1:])) for key in keys]

    UpsertItem.query.bulk_upsert(
        items,
        update_fields=[UpsertItem.value],
        unique_fields=[UpsertItem.key],
        batch_size=2,
    )

    assert [item.key for item in items] == keys  # caller's order preserved
    for item in items:
        if item.key in seeded:
            assert item.id == seeded[item.key]
        assert item.id is not None

    assert UpsertItem.query.count() == 8
    assert {row.key: row.value for row in UpsertItem.query.all()} == {
        f"k{index}": index for index in range(8)
    }


def test_bulk_upsert_repeated_update_field_rejected(db):
    # Postgres assigns each column once per statement; naming one twice is a
    # syntax error mid-transaction, so it's caught at the call instead.
    with pytest.raises(ValueError, match=r"names \['value'\] more than once"):
        UpsertItem.query.bulk_upsert(
            [UpsertItem(key="a", value=1)],
            update_fields=[UpsertItem.value, UpsertItem.value],
            unique_fields=[UpsertItem.key],
        )


def test_bulk_upsert_repeated_update_field_rejected_before_any_query(db):
    # Validation happens at the call, so an empty objs list is checked too.
    with pytest.raises(ValueError, match="more than once"):
        UpsertItem.query.bulk_upsert(
            [],
            update_fields=[UpsertItem.value, UpsertItem.value],
            unique_fields=[UpsertItem.key],
        )


def test_bulk_upsert_unsaved_related_object_names_bulk_upsert(db):
    # The guard is shared with bulk_create(); the message has to name the call
    # the user actually made.
    with pytest.raises(ValueError, match=r"^bulk_upsert\(\) prohibited"):
        UpsertScoped.query.bulk_upsert(
            [UpsertScoped(tenant=UpsertTenant(name="unsaved"), slug="s", value=1)],
            update_fields=[UpsertScoped.value],
            unique_fields=[UpsertScoped.tenant, UpsertScoped.slug],
        )


def test_bulk_upsert_decimal_key_conflicts_across_scales(db):
    # numeric(12,4) stores 1.0 and 1.00 as the same value, so the second call
    # has to find the first one's row rather than insert beside it.
    first = [UpsertDecimalKey(amount=Decimal("1.0"), value=1)]
    UpsertDecimalKey.query.bulk_upsert(
        first,
        update_fields=[UpsertDecimalKey.value],
        unique_fields=[UpsertDecimalKey.amount],
    )

    second = [UpsertDecimalKey(amount=Decimal("1.00"), value=2)]
    UpsertDecimalKey.query.bulk_upsert(
        second,
        update_fields=[UpsertDecimalKey.value],
        unique_fields=[UpsertDecimalKey.amount],
    )

    assert second[0].id == first[0].id
    assert UpsertDecimalKey.query.count() == 1
    assert UpsertDecimalKey.query.get(id=first[0].id).value == 2


def test_bulk_upsert_decimal_key_conflicts_across_signed_zero(db):
    zero = [UpsertDecimalKey(amount=Decimal("0.0"), value=1)]
    UpsertDecimalKey.query.bulk_upsert(
        zero,
        update_fields=[UpsertDecimalKey.value],
        unique_fields=[UpsertDecimalKey.amount],
    )

    negative_zero = [UpsertDecimalKey(amount=Decimal("-0.00"), value=2)]
    UpsertDecimalKey.query.bulk_upsert(
        negative_zero,
        update_fields=[UpsertDecimalKey.value],
        unique_fields=[UpsertDecimalKey.amount],
    )

    assert negative_zero[0].id == zero[0].id
    assert UpsertDecimalKey.query.count() == 1


def test_bulk_upsert_decimal_keys_at_different_scales_in_one_batch(db):
    # Postgres holds these equal, so they are the same row twice in one
    # statement -- the sort renders them identically, and the cardinality
    # violation is reported as the duplicate it is.
    with pytest.raises(ValueError, match=r"same \['amount'\] in one statement"):
        UpsertDecimalKey.query.bulk_upsert(
            [
                UpsertDecimalKey(amount=Decimal("1.0"), value=1),
                UpsertDecimalKey(amount=Decimal("1.000"), value=2),
            ],
            update_fields=[UpsertDecimalKey.value],
            unique_fields=[UpsertDecimalKey.amount],
        )

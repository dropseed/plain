"""QuerySet.returning() captures the rows touched by update() and delete().

Without returning(), update()/delete() return an int rowcount as always.
With it, no-arg returning() hydrates full model instances and
returning(*Model.field) returns a list of dicts holding just those columns.
"""

from __future__ import annotations

import copy
import operator
import re
from typing import TYPE_CHECKING, cast

import psycopg
import pytest
from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.querysets import CustomQuerySet, CustomQuerySetModel
from app.examples.models.relationships import Widget
from app.examples.models.returning import ReturningEvent
from app.examples.models.upsert import UpsertItem
from plain.postgres import transaction
from plain.postgres.db import get_connection
from plain.postgres.exceptions import FieldError
from plain.postgres.sources import build_connection_params
from plain.postgres.transaction import TransactionManagementError

if TYPE_CHECKING:
    from typing import LiteralString


def _seed_events() -> None:
    ReturningEvent(label="a", count=1, payload={"n": 1}).create()
    ReturningEvent(label="a", count=1, payload={"n": 2}).create()
    ReturningEvent(label="b", count=1, payload=None).create()


# ===========================================================================
# update()
# ===========================================================================


def test_update_without_returning_returns_int(db):
    _seed_events()
    result = ReturningEvent.query.filter(label="a").update(count=5)
    assert result == 2


def test_update_returning_instances_reflect_new_values(db):
    _seed_events()
    rows = ReturningEvent.query.filter(label="a").returning().update(count=9)

    assert len(rows) == 2
    assert all(isinstance(row, ReturningEvent) for row in rows)
    # RETURNING on UPDATE reports the post-update values.
    assert {row.count for row in rows} == {9}
    # JSON converters are applied — payload comes back as a dict, not a string.
    payloads = [row.payload for row in rows]
    assert {p["n"] for p in payloads if p} == {1, 2}


def test_update_returning_named_fields_are_dicts(db):
    _seed_events()
    rows = (
        ReturningEvent.query.filter(label="a")
        .returning(ReturningEvent.id, ReturningEvent.count)
        .update(count=7)
    )

    assert len(rows) == 2
    assert all(isinstance(row, dict) for row in rows)
    assert all(set(row) == {"id", "count"} for row in rows)
    assert {row["count"] for row in rows} == {7}


def test_update_returning_empty_result_is_empty_list(db):
    _seed_events()
    rows = ReturningEvent.query.filter(label="missing").returning().update(count=1)
    assert rows == []


# ===========================================================================
# delete()
# ===========================================================================


def test_delete_without_returning_returns_int(db):
    _seed_events()
    result = ReturningEvent.query.filter(label="a").delete()
    assert result == 2


def test_delete_returning_named_fields_gives_deleted_rows(db):
    _seed_events()
    rows = (
        ReturningEvent.query.filter(label="a")
        .returning(ReturningEvent.id, ReturningEvent.payload)
        .delete()
    )

    assert len(rows) == 2
    assert all(isinstance(row, dict) and set(row) == {"id", "payload"} for row in rows)
    # DELETE ... RETURNING reports the rows as they were.
    assert {tuple(row["payload"].items()) for row in rows} == {
        (("n", 1),),
        (("n", 2),),
    }
    assert not ReturningEvent.query.filter(label="a").exists()


def test_delete_returning_instances(db):
    _seed_events()
    rows = ReturningEvent.query.filter(label="b").returning().delete()

    assert len(rows) == 1
    assert isinstance(rows[0], ReturningEvent)
    assert rows[0].label == "b"


def test_delete_returning_empty_result_is_empty_list(db):
    rows = (
        ReturningEvent.query.filter(label="missing")
        .returning(ReturningEvent.id)
        .delete()
    )
    assert rows == []


# ===========================================================================
# Validation and typing
# ===========================================================================


def _seed_custom() -> None:
    CustomQuerySetModel(name="custom one").create()
    CustomQuerySetModel(name="other").create()


def test_custom_queryset_method_before_returning(db):
    _seed_custom()
    rows = CustomQuerySetModel.query.get_custom().returning().update(name="claimed")

    assert [row.name for row in rows] == ["claimed"]


def test_custom_queryset_method_after_returning(db):
    # returning() sets state; it does not swap the class out from under a
    # custom QuerySet, so the model's own methods still chain after it.
    _seed_custom()
    qs = CustomQuerySetModel.query.returning()
    assert isinstance(qs, CustomQuerySet)

    rows = qs.get_custom().update(name="claimed")
    assert [row.name for row in rows] == ["claimed"]


def test_returning_state_survives_further_chaining(db):
    _seed_events()
    qs = ReturningEvent.query.returning(ReturningEvent.id).filter(label="a")
    assert type(qs) is type(ReturningEvent.query)

    rows = qs.update(count=2)
    assert all(set(row) == {"id"} for row in rows)


def test_returning_string_arg_errors(db):
    with pytest.raises(TypeError, match="takes field references, not strings"):
        ReturningEvent.query.returning("count")  # ty: ignore[invalid-argument-type]


def test_returning_wrong_model_field_errors(db):
    with pytest.raises(FieldError, match="belongs to a different model"):
        ReturningEvent.query.returning(DeleteParent.name)


def test_returning_before_filter_is_preserved(db):
    _seed_events()
    rows = ReturningEvent.query.returning().filter(label="a").update(count=3)
    assert len(rows) == 2
    assert {row.count for row in rows} == {3}


def test_returning_then_values_update_errors(db):
    # .values() + returning() is nonsensical; it must not silently misbehave.
    with pytest.raises(TypeError, match="after .values"):
        ReturningEvent.query.returning().values("id").update(count=1)


# ===========================================================================
# FK cascade — RETURNING only reports the target table's rows
# ===========================================================================


def test_delete_returning_excludes_cascade_deleted_children(db):
    parent = DeleteParent(name="p").create()
    ChildCascade(parent=parent).create()
    ChildCascade(parent=parent).create()

    rows = (
        DeleteParent.query.filter(id=parent.id)
        .returning(DeleteParent.id, DeleteParent.name)
        .delete()
    )

    # Only the parent row comes back, even though two children were cascaded.
    assert len(rows) == 1
    assert rows[0] == {"id": parent.id, "name": "p"}
    assert ChildCascade.query.count() == 0


# ===========================================================================
# Joins — the WHERE id IN (subquery) rewrite keeps RETURNING
# ===========================================================================


def test_update_returning_across_a_relation(db, capture_queries):
    keep = DeleteParent(name="keep").create()
    move = DeleteParent(name="move").create()
    ChildCascade(parent=move).create()
    ChildCascade(parent=move).create()
    ChildCascade(parent=keep).create()

    with capture_queries() as queries:
        rows = (
            ChildCascade.query.filter(parent__name="move")
            .returning(ChildCascade.id)
            .update(parent=keep)
        )

    # Filtering across the FK rewrites the UPDATE to `WHERE id IN (subquery)`;
    # RETURNING has to survive that rewrite, in one statement.
    assert len(queries) == 1
    assert "RETURNING" in queries[0]["sql"]
    assert len(rows) == 2
    assert ChildCascade.query.filter(parent=keep).count() == 3


def test_delete_returning_across_a_relation(db, capture_queries):
    parent = DeleteParent(name="doomed").create()
    ChildCascade(parent=parent).create()
    ChildCascade(parent=parent).create()

    with capture_queries() as queries:
        rows = ChildCascade.query.filter(parent__name="doomed").returning().delete()

    assert len(queries) == 1
    assert "RETURNING" in queries[0]["sql"]
    assert len(rows) == 2
    assert all(row.parent.id == parent.id for row in rows)


# ===========================================================================
# Foreign key columns
# ===========================================================================


@pytest.mark.parametrize(
    "reference",
    [
        lambda: ChildCascade.parent,
        lambda: Widget.tags,
        lambda: DeleteParent.childcascade_set,
    ],
    ids=["forward_fk", "many_to_many", "reverse_fk"],
)
def test_returning_relation_reference_errors(db, reference):
    # At class level a relation attribute is its descriptor -- that is what
    # lets where() traverse it -- so none of them is a column reference. Say
    # that, for every kind, instead of dumping the descriptor's repr.
    with pytest.raises(FieldError, match="it is a relation, not a column"):
        ChildCascade.query.returning(reference())


def test_returning_instances_carry_foreign_keys(db):
    parent = DeleteParent(name="p").create()
    ChildCascade(parent=parent).create()

    rows = ChildCascade.query.returning().delete()

    assert len(rows) == 1
    assert rows[0].parent.id == parent.id


# ===========================================================================
# Writes that RETURNING doesn't apply to say so
# ===========================================================================


@pytest.mark.parametrize(
    "write",
    [
        lambda qs: qs.create(label="x", count=1),
        lambda qs: qs.bulk_create([ReturningEvent(label="x", count=1)]),
        lambda qs: qs.bulk_upsert(
            [ReturningEvent(label="x", count=1)],
            update_fields=[ReturningEvent.count],
            unique_fields=[ReturningEvent.id],
        ),
        lambda qs: qs.bulk_update(list(ReturningEvent.query), ["count"]),
        lambda qs: qs.get_or_create(label="x", count=1),
        # ReturningEvent declares no UniqueConstraint, and upsert() refuses
        # to conflict on the primary key, so this one case uses a model that
        # has a real conflict target -- otherwise the call would fail for a
        # reason other than the one under test.
        lambda _qs: UpsertItem.query.returning().upsert(
            key="x",
            value=1,
            unique_fields=[UpsertItem.key],
        ),
    ],
    ids=[
        "create",
        "bulk_create",
        "bulk_upsert",
        "bulk_update",
        "get_or_create",
        "upsert",
    ],
)
def test_returning_rejects_other_writes(db, write):
    ReturningEvent(label="seed", count=1).create()
    with pytest.raises(
        TypeError, match="only applies to update\\(\\) and delete\\(\\)"
    ):
        write(ReturningEvent.query.returning())


# ===========================================================================
# row locks
# ===========================================================================


def test_lock_then_returning_update(db, capture_queries):
    # Locking the read side of a write is the job-claim pattern, so a lock
    # must not trip _reject_returning() -- update() still hands back rows.
    _seed_events()
    qs = ReturningEvent.query.filter(label="a").for_update()
    rows = qs.returning().update(count=4)

    assert {row.count for row in rows} == {4}


def test_returning_then_lock_keeps_the_returning_state(db):
    # The other order too: for_update() chains off a returning() queryset
    # without dropping the returning state or hitting the lock guard.
    _seed_events()
    qs = ReturningEvent.query.filter(label="a").returning().for_update()

    rows = qs.update(count=6)
    assert {row.count for row in rows} == {6}


def test_lock_then_returning_delete(db):
    _seed_events()
    rows = (
        ReturningEvent.query.filter(label="a")
        .for_update()
        .returning(ReturningEvent.label)
        .delete()
    )

    assert [row["label"] for row in rows] == ["a", "a"]
    assert ReturningEvent.query.count() == 1


def test_lock_survives_into_the_subquery_of_a_joined_returning_update(
    db, capture_queries
):
    # A join forces update() through an `id IN (SELECT ...)` rewrite. That
    # inner select is where the lock belongs, and RETURNING rides on the
    # outer UPDATE.
    parent = DeleteParent(name="p").create()
    child = ChildCascade(parent=parent).create()

    with capture_queries() as queries:
        rows = (
            ChildCascade.query.filter(parent__name="p")
            .for_update(skip_locked=True)
            .returning()
            .update(parent=parent)
        )

    sql = " ".join(q["sql"] for q in queries)
    assert re.search(r"FOR UPDATE OF \w+ SKIP LOCKED", sql)
    assert "RETURNING" in sql
    assert [row.id for row in rows] == [child.id]


# ===========================================================================
# A locked write claims rows exclusively
#
# Neither UPDATE nor DELETE takes a locking clause of its own, so a locked
# write has to put the lock on the sub-select that picks the rows. Without
# that the lock is silently dropped and two workers claim the same rows.
# ===========================================================================


def test_locked_update_puts_the_lock_in_the_subquery(db, capture_queries, executed_sql):
    # Single table, no joins -- the case that used to skip the rewrite.
    _seed_events()
    with capture_queries() as queries:
        ReturningEvent.query.filter(label="a").for_update(
            skip_locked=True
        ).returning().update(count=4)

    sql = executed_sql(queries)
    before_returning = sql.split("RETURNING")[0]
    assert re.search(r"FOR UPDATE OF \w+ SKIP LOCKED\)", before_returning)
    assert before_returning.index("IN (SELECT") < before_returning.index("FOR UPDATE")


def test_locked_delete_puts_the_lock_in_the_subquery(db, capture_queries, executed_sql):
    _seed_events()
    with capture_queries() as queries:
        ReturningEvent.query.filter(label="a").for_update(
            skip_locked=True
        ).returning().delete()

    sql = executed_sql(queries)
    before_returning = sql.split("RETURNING")[0]
    assert re.search(r"FOR UPDATE OF \w+ SKIP LOCKED\)", before_returning)
    assert before_returning.index("IN (SELECT") < before_returning.index("FOR UPDATE")


def _race(sql: str) -> tuple[set, set]:
    """Run `sql` from two sessions, the first holding its transaction open."""
    # psycopg types execute() as LiteralString to discourage string-built SQL;
    # this statement came out of the ORM's own compiler.
    statement = cast("LiteralString", sql)
    params = build_connection_params(get_connection().settings_dict)
    with (
        psycopg.connect(**params) as first,
        psycopg.connect(**params) as second,
    ):
        with first.cursor() as cur_first, second.cursor() as cur_second:
            cur_first.execute(statement)
            claimed_first = {row[0] for row in cur_first.fetchall()}
            # Without SKIP LOCKED on the inner select the second session
            # would block on the first session's row locks until this fires.
            cur_second.execute("SET lock_timeout = '2s'")
            cur_second.execute(statement)
            claimed_second = {row[0] for row in cur_second.fetchall()}
        first.rollback()
        second.rollback()
    return claimed_first, claimed_second


def test_locked_returning_update_claims_rows_exclusively(
    isolated_db, capture_queries, executed_sql
):
    # Capture the statement while nothing matches, so the rows the two
    # sessions race for are still unclaimed. The race replays it on raw
    # connections -- the harness swaps the ORM's connection per context, so
    # a second session can't go through the ORM.
    with capture_queries() as queries, transaction.atomic():
        ReturningEvent.query.filter(label="claim").for_update(
            skip_locked=True
        ).returning(ReturningEvent.id).update(count=1)
    sql = executed_sql(queries)

    for _ in range(4):
        ReturningEvent(label="claim", count=0).create()

    claimed_first, claimed_second = _race(sql)

    assert len(claimed_first) == 4
    assert claimed_second == set()
    assert not claimed_first & claimed_second


def test_locked_returning_delete_claims_rows_exclusively(
    isolated_db, capture_queries, executed_sql
):
    with capture_queries() as queries, transaction.atomic():
        ReturningEvent.query.filter(label="claim").for_update(
            skip_locked=True
        ).returning(ReturningEvent.id).delete()
    sql = executed_sql(queries)

    for _ in range(4):
        ReturningEvent(label="claim", count=0).create()

    claimed_first, claimed_second = _race(sql)

    assert len(claimed_first) == 4
    assert claimed_second == set()
    assert not claimed_first & claimed_second


# ===========================================================================
# Combining querysets
#
# The combined query emits one RETURNING clause, so the state has to survive
# the combination from either side -- and two different selections can't both
# be honored.
# ===========================================================================


def test_or_carries_returning_from_the_left(db):
    _seed_events()
    combined = ReturningEvent.query.filter(label="a").returning() | (
        ReturningEvent.query.filter(label="b")
    )

    rows = combined.update(count=7)
    assert {row.count for row in rows} == {7}
    assert len(rows) == 3


def test_or_carries_returning_from_the_right(db):
    _seed_events()
    combined = ReturningEvent.query.filter(label="a") | (
        ReturningEvent.query.filter(label="b").returning()
    )

    rows = combined.update(count=7)
    assert {row.count for row in rows} == {7}
    assert len(rows) == 3


def test_and_carries_returning_from_the_right(db):
    _seed_events()
    combined = ReturningEvent.query.filter(label="a") & (
        ReturningEvent.query.filter(count=1).returning(ReturningEvent.id)
    )

    rows = combined.update(count=7)
    assert len(rows) == 2
    assert all(set(row) == {"id"} for row in rows)


@pytest.mark.parametrize("op", [operator.or_, operator.and_])
def test_combining_different_returning_selections_errors(db, op):
    left = ReturningEvent.query.filter(label="a").returning()
    right = ReturningEvent.query.filter(label="b").returning(ReturningEvent.id)

    with pytest.raises(TypeError, match="one RETURNING clause"):
        op(left, right)


def test_none_keeps_returning_and_writes_nothing(db, capture_queries):
    _seed_events()
    empty = ReturningEvent.query.returning().none()

    with capture_queries() as queries:
        assert empty.update(count=9) == []
        assert empty.delete() == []

    assert queries == []
    assert ReturningEvent.query.count() == 3


# ===========================================================================
# Deleted rows come back as snapshots
# ===========================================================================


def test_deleted_instances_keep_their_data(db):
    seeded = ReturningEvent(label="gone", count=3, payload={"n": 1}).create()

    (row,) = ReturningEvent.query.filter(label="gone").returning().delete()

    # The id is the point of a delete-with-RETURNING: it is what lets the
    # caller correlate the row with whatever it was tracking.
    assert row.id == seeded.id
    assert row.label == "gone"
    assert row.count == 3
    assert row.payload == {"n": 1}


@pytest.mark.parametrize("method", ["create", "update", "delete"])
def test_deleted_instances_refuse_writes(db, method):
    ReturningEvent(label="gone", count=3).create()
    (row,) = ReturningEvent.query.filter(label="gone").returning().delete()

    # Every write says the same thing, because there is one reason: the row
    # this instance describes is gone.
    with pytest.raises(ValueError, match="snapshot of a row that returning"):
        getattr(row, method)()


def test_updated_instances_are_still_live(db):
    # Only the delete path marks snapshots -- update() hands back rows that
    # are still there and still writable.
    _seed_events()
    (row, _) = ReturningEvent.query.filter(label="a").returning().update(count=5)

    row.count = 6
    row.update()

    assert ReturningEvent.query.get(id=row.id).count == 6


# ===========================================================================
# returning() is inert for reads
# ===========================================================================


def test_reads_on_a_returning_queryset_are_unaffected(db):
    # returning() describes what the *next write* hands back. Reads on the
    # same queryset behave exactly as they would without it -- rejecting
    # them would break inspecting a chain before writing it.
    _seed_events()
    qs = ReturningEvent.query.filter(label="a").returning()

    assert qs.count() == 2
    assert qs.exists()
    assert isinstance(qs.first(), ReturningEvent)
    assert len(list(qs)) == 2
    assert [row["label"] for row in qs.values("label")] == ["a", "a"]

    # And the state is still there for the write that follows.
    assert {row.count for row in qs.update(count=4)} == {4}


# ===========================================================================
# A locked write needs a transaction
# ===========================================================================


@pytest.mark.parametrize("write", ["update", "delete"])
def test_locked_write_outside_a_transaction_raises(isolated_db, write):
    # The lock now lands on a sub-select, which Postgres only honors inside a
    # transaction -- so the write refuses rather than running unlocked, the
    # way it used to.
    ReturningEvent(label="a", count=1).create()
    qs = ReturningEvent.query.filter(label="a").for_update(skip_locked=True)

    with pytest.raises(TransactionManagementError, match="outside of a transaction"):
        qs.update(count=2) if write == "update" else qs.delete()

    # The row is untouched, and the same write inside atomic() goes through.
    with transaction.atomic():
        assert ReturningEvent.query.filter(label="a").for_update().update(count=2) == 1


@pytest.mark.parametrize(
    "narrow",
    [
        lambda qs: qs.defer("payload"),
        lambda qs: qs.only("label"),
        lambda qs: qs.reverse(),
    ],
    ids=["defer", "only", "reverse"],
)
def test_column_selection_keeps_the_returning_state(db, narrow):
    # defer()/only()/reverse() shape a read; the write after them still
    # hands back rows, and whole ones -- no-arg returning() selects every
    # column regardless of what was deferred.
    _seed_events()
    rows = narrow(ReturningEvent.query.filter(label="a").returning()).update(count=8)

    assert len(rows) == 2
    assert {row.count for row in rows} == {8}
    assert all(row.payload is not None for row in rows)


def test_deepcopy_of_a_returning_queryset_still_combines(db):
    # deepcopy() copies the Field objects, so comparing the selections by
    # identity called a queryset and its own copy a mismatch.
    _seed_events()
    qs = ReturningEvent.query.filter(label="a").returning()

    combined = copy.deepcopy(qs) | qs

    rows = combined.update(count=5)
    assert {row.count for row in rows} == {5}

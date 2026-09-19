"""QuerySet.returning() captures the rows touched by update() and delete().

Without returning(), update()/delete() return an int rowcount as always.
With it, no-arg returning() hydrates full model instances and
returning(*Model.field) returns a list of dicts holding just those columns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import psycopg
import pytest
from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.returning import ReturningEvent
from plain.postgres import ReturningQuerySet, transaction
from plain.postgres.db import get_connection
from plain.postgres.exceptions import FieldError
from plain.postgres.sources import build_connection_params

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


def test_returning_returns_a_returning_queryset(db):
    assert isinstance(ReturningEvent.query.returning(), ReturningQuerySet)
    assert isinstance(
        ReturningEvent.query.returning(ReturningEvent.id), ReturningQuerySet
    )


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


def test_returning_relation_reference_errors(db):
    # Model.fk is the relation, not the column, so it has no spelling here --
    # say that instead of dumping the descriptor's repr.
    with pytest.raises(FieldError, match="it is a relation, not a column"):
        ChildCascade.query.returning(ChildCascade.parent)  # ty: ignore[invalid-argument-type]


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
        lambda qs: qs.bulk_update(list(ReturningEvent.query), ["count"]),
        lambda qs: qs.get_or_create(label="x", count=1),
        lambda qs: qs.update_or_create(label="x", defaults={"count": 1}),
    ],
    ids=["create", "bulk_create", "bulk_update", "get_or_create", "update_or_create"],
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
    assert isinstance(qs.returning(), ReturningQuerySet)
    rows = qs.returning().update(count=4)

    assert {row.count for row in rows} == {4}


def test_returning_then_lock_keeps_the_returning_queryset(db):
    # The other order too: for_update() chains off a ReturningQuerySet
    # without dropping the returning state or hitting the lock guard.
    _seed_events()
    qs = ReturningEvent.query.filter(label="a").returning().for_update()

    assert isinstance(qs, ReturningQuerySet)
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
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "RETURNING" in sql
    assert [row.id for row in rows] == [child.id]


# ===========================================================================
# A locked write claims rows exclusively
#
# Neither UPDATE nor DELETE takes a locking clause of its own, so a locked
# write has to put the lock on the sub-select that picks the rows. Without
# that the lock is silently dropped and two workers claim the same rows.
# ===========================================================================


def _only_sql(queries: list[dict]) -> str:
    assert len(queries) == 1, [q["sql"] for q in queries]
    return queries[0]["sql"]


def test_locked_update_puts_the_lock_in_the_subquery(db, capture_queries):
    # Single table, no joins -- the case that used to skip the rewrite.
    _seed_events()
    with capture_queries() as queries:
        ReturningEvent.query.filter(label="a").for_update(
            skip_locked=True
        ).returning().update(count=4)

    sql = _only_sql(queries)
    before_returning = sql.split("RETURNING")[0]
    assert "FOR UPDATE SKIP LOCKED)" in before_returning
    assert before_returning.index("IN (SELECT") < before_returning.index("FOR UPDATE")


def test_locked_delete_puts_the_lock_in_the_subquery(db, capture_queries):
    _seed_events()
    with capture_queries() as queries:
        ReturningEvent.query.filter(label="a").for_update(
            skip_locked=True
        ).returning().delete()

    sql = _only_sql(queries)
    before_returning = sql.split("RETURNING")[0]
    assert "FOR UPDATE SKIP LOCKED)" in before_returning
    assert before_returning.index("IN (SELECT") < before_returning.index("FOR UPDATE")


def _capture_locked_write(write) -> str:
    """Run `write` against rows that don't exist yet and return its SQL.

    The statement is what the race below replays on two raw connections --
    the pytest harness swaps the connection per context, so a second session
    can't go through the ORM.
    """
    conn = get_connection()
    previous = conn.force_debug_cursor
    conn.force_debug_cursor = True
    conn.queries_log.clear()
    try:
        with transaction.atomic():
            write()
        captured = [q for q in conn.queries_log if q["sql"] not in ("BEGIN", "COMMIT")]
    finally:
        conn.force_debug_cursor = previous
    return _only_sql(captured)


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


def test_locked_returning_update_claims_rows_exclusively(isolated_db):
    sql = _capture_locked_write(
        lambda: (
            ReturningEvent.query.filter(label="claim")
            .for_update(skip_locked=True)
            .returning(ReturningEvent.id)
            .update(count=1)
        )
    )
    for _ in range(4):
        ReturningEvent(label="claim", count=0).create()

    claimed_first, claimed_second = _race(sql)

    assert len(claimed_first) == 4
    assert claimed_second == set()
    assert not claimed_first & claimed_second


def test_locked_returning_delete_claims_rows_exclusively(isolated_db):
    sql = _capture_locked_write(
        lambda: (
            ReturningEvent.query.filter(label="claim")
            .for_update(skip_locked=True)
            .returning(ReturningEvent.id)
            .delete()
        )
    )
    for _ in range(4):
        ReturningEvent(label="claim", count=0).create()

    claimed_first, claimed_second = _race(sql)

    assert len(claimed_first) == 4
    assert claimed_second == set()
    assert not claimed_first & claimed_second

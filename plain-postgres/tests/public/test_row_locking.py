"""
Row-level locking: for_update(), for_no_key_update(), for_share(), and
for_key_share() emit the matching Postgres locking clause and options.
"""

from __future__ import annotations

import re

import psycopg
import pytest
from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.relationships import Widget
from plain.postgres import transaction
from plain.postgres.aggregates import Count
from plain.postgres.db import get_connection
from plain.postgres.expressions import Value, Window
from plain.postgres.functions import RowNumber
from plain.postgres.sources import build_connection_params
from plain.postgres.transaction import TransactionManagementError
from psycopg import NotSupportedError


@pytest.mark.parametrize(
    ("method", "clause"),
    [
        ("for_update", "FOR UPDATE"),
        ("for_no_key_update", "FOR NO KEY UPDATE"),
        ("for_share", "FOR SHARE"),
        ("for_key_share", "FOR KEY SHARE"),
    ],
)
def test_lock_method_emits_its_clause(
    db, capture_queries, executed_sql, method, clause
):
    with capture_queries() as queries:
        list(getattr(Widget.query, method)())
    assert clause in executed_sql(queries)


def test_nowait_appends_nowait(db, capture_queries, executed_sql):
    with capture_queries() as queries:
        list(Widget.query.for_update(nowait=True))
    assert "FOR UPDATE NOWAIT" in executed_sql(queries)


def test_skip_locked_appends_skip_locked(db, capture_queries, executed_sql):
    with capture_queries() as queries:
        list(Widget.query.for_share(skip_locked=True))
    assert "FOR SHARE SKIP LOCKED" in executed_sql(queries)


def test_of_restricts_lock_to_named_table(db, capture_queries, executed_sql):
    with capture_queries() as queries:
        list(Widget.query.for_update(of=("self",)))
    assert "FOR UPDATE OF" in executed_sql(queries)


def test_nowait_and_skip_locked_together_raise():
    with pytest.raises(ValueError, match="nowait"):
        Widget.query.for_update(nowait=True, skip_locked=True)


def test_last_lock_mode_wins(db, capture_queries, executed_sql):
    with capture_queries() as queries:
        list(Widget.query.for_update().for_share())
    sql = executed_sql(queries)
    assert "FOR SHARE" in sql
    assert "FOR UPDATE" not in sql


def test_lock_requires_a_transaction(isolated_db):
    # isolated_db (unlike db) leaves the connection in autocommit, so this is
    # a genuine "no open transaction" call. The message names the mode that
    # was actually requested, not a hardcoded FOR UPDATE.
    with pytest.raises(TransactionManagementError, match="FOR SHARE"):
        list(Widget.query.for_share())


def test_lock_works_inside_atomic(db):
    Widget.query.create(name="W", size="L")
    with transaction.atomic():
        widgets = list(Widget.query.for_update())
    assert len(widgets) == 1


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("for_update", "for_update()"),
        ("for_no_key_update", "for_no_key_update()"),
        ("for_share", "for_share()"),
        ("for_key_share", "for_key_share()"),
    ],
)
def test_lock_after_distinct_raises(db, method, expected):
    with pytest.raises(NotSupportedError, match=re.escape(expected)):
        getattr(Widget.query.distinct(), method)()


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("for_update", "for_update()"),
        ("for_no_key_update", "for_no_key_update()"),
        ("for_share", "for_share()"),
        ("for_key_share", "for_key_share()"),
    ],
)
def test_distinct_after_lock_raises(db, method, expected):
    with pytest.raises(NotSupportedError, match=re.escape(expected)):
        getattr(Widget.query, method)().distinct()


def test_lock_after_distinct_on_raises(db):
    with pytest.raises(NotSupportedError, match=r"distinct\(\)"):
        Widget.query.distinct("size").for_update()


def test_lock_after_aggregate_annotation_raises(db):
    with pytest.raises(NotSupportedError, match="aggregate annotation"):
        Widget.query.annotate(n=Count("id")).for_share()


def test_aggregate_annotation_after_lock_raises(db):
    with pytest.raises(NotSupportedError, match="aggregate annotation"):
        Widget.query.for_share().annotate(n=Count("id"))


def test_values_aggregate_annotation_after_lock_raises(db):
    with pytest.raises(NotSupportedError, match="aggregate annotation"):
        Widget.query.for_update().values("size").annotate(n=Count("id"))


def test_non_aggregate_annotation_is_allowed_with_a_lock(
    db, capture_queries, executed_sql
):
    # Only aggregation forces a GROUP BY; a plain expression annotation leaves
    # the rows mapping one-to-one onto table rows, so Postgres can lock them.
    with capture_queries() as queries:
        list(Widget.query.for_update().annotate(label=Value("x")))
    assert "FOR UPDATE" in executed_sql(queries)


def test_lock_after_window_annotation_raises(db):
    with pytest.raises(NotSupportedError, match="window annotation"):
        Widget.query.annotate(rn=Window(RowNumber())).for_update()


def test_window_annotation_after_lock_raises(db):
    with pytest.raises(NotSupportedError, match="window annotation"):
        Widget.query.for_update().annotate(rn=Window(RowNumber()))


def test_count_and_aggregate_still_drop_the_lock(db, capture_queries, executed_sql):
    # Unchanged by the up-front guards: both compile to an aggregate query of
    # their own, so the lock is dropped rather than rejected.
    with capture_queries() as queries:
        assert Widget.query.for_update().count() == 0
    assert "FOR UPDATE" not in executed_sql(queries)

    with capture_queries() as queries:
        assert Widget.query.for_update().aggregate(n=Count("id")) == {"n": 0}
    assert "FOR UPDATE" not in executed_sql(queries)


# ---------------------------------------------------------------------------
# Set-based writes
#
# Neither UPDATE nor DELETE takes a locking clause, so the lock has to move
# onto the sub-select that picks the rows rather than being dropped.
# ---------------------------------------------------------------------------


def test_locked_update_locks_in_a_subquery(db, capture_queries, executed_sql):
    with capture_queries() as queries:
        Widget.query.for_update(skip_locked=True).update(name="x")

    sql = executed_sql(queries)
    assert "IN (SELECT" in sql
    # OF names the written table, so the lock can't spread to a joined one.
    assert re.search(r"FOR UPDATE OF \w+ SKIP LOCKED\)", sql)


def test_locked_delete_locks_in_a_subquery(db, capture_queries, executed_sql):
    with capture_queries() as queries:
        Widget.query.for_update(skip_locked=True).delete()

    sql = executed_sql(queries)
    assert "IN (SELECT" in sql
    # OF names the written table, so the lock can't spread to a joined one.
    assert re.search(r"FOR UPDATE OF \w+ SKIP LOCKED\)", sql)


def test_unlocked_writes_stay_a_flat_statement(db, capture_queries, executed_sql):
    with capture_queries() as queries:
        Widget.query.update(name="x")

    assert "IN (SELECT" not in executed_sql(queries)


def test_bulk_update_drops_the_lock(db, capture_queries, executed_sql):
    # bulk_update targets rows by id, so the lock has nothing to guard --
    # the batches stay flat instead of each becoming a locking sub-select.
    widgets = [
        Widget(name="a", size="s").create(),
        Widget(name="b", size="s").create(),
    ]
    for index, widget in enumerate(widgets):
        widget.name = f"renamed-{index}"

    with capture_queries() as queries:
        assert Widget.query.for_update().bulk_update(widgets, ["name"]) == 2

    sql = executed_sql(queries)
    assert "IN (SELECT" not in sql
    assert "FOR UPDATE" not in sql


@pytest.mark.parametrize("write", ["update", "delete"])
def test_related_lock_target_is_refused_on_a_write(db, write):
    # A locked write runs as `id IN (SELECT id ... FOR UPDATE OF ...)`, and
    # that sub-select reads one column: this table's id. There is nothing for
    # OF to name but this table -- say so here rather than let the compiler
    # raise FieldError a long way from the call.
    parent = DeleteParent(name="p").create()
    ChildCascade(parent=parent).create()
    qs = ChildCascade.query.filter(parent__name="p").for_update(of=("parent",))

    with pytest.raises(TypeError, match=r"locks only the rows it writes"):
        qs.update(parent=parent) if write == "update" else qs.delete()


def test_related_lock_target_is_still_fine_on_a_read(db, capture_queries, executed_sql):
    # Only the write is narrowed -- the read still locks the parent rows.
    parent = DeleteParent(name="p").create()
    ChildCascade(parent=parent).create()

    with capture_queries() as queries:
        list(
            ChildCascade.query.select_related("parent")
            .filter(parent__name="p")
            .for_update(of=("parent",))
        )

    assert 'FOR UPDATE OF "examples_deleteparent"' in executed_sql(queries)


def test_self_lock_target_works_on_a_joined_write(db, capture_queries, executed_sql):
    parent = DeleteParent(name="p").create()
    other = DeleteParent(name="other").create()
    ChildCascade(parent=parent).create()
    ChildCascade(parent=parent).create()

    with capture_queries() as queries:
        moved = (
            ChildCascade.query.filter(parent__name="p")
            .for_update(of=("self",))
            .update(parent=other)
        )

    assert moved == 2
    sql = executed_sql(queries)
    # The join the filter needed rides along in the sub-select, and OF names
    # the outer table's alias inside it.
    assert "INNER JOIN" in sql
    assert "FOR UPDATE OF" in sql.split("RETURNING")[0]
    assert ChildCascade.query.filter(parent=other).count() == 2


def test_locked_write_locks_only_its_own_table(db, capture_queries, executed_sql):
    # A bare FOR UPDATE would lock a row in every table the sub-select reads,
    # including the one the filter only joined to look a value up.
    parent = DeleteParent(name="p").create()
    ChildCascade(parent=parent).create()

    with capture_queries() as queries:
        ChildCascade.query.filter(parent__name="p").for_update(
            skip_locked=True
        ).delete()

    sql = executed_sql(queries)
    assert "INNER JOIN" in sql
    assert "FOR UPDATE OF" in sql


@pytest.mark.parametrize("write", ["update", "delete"])
def test_locked_write_is_not_blocked_by_a_joined_row(isolated_db, write):
    # The filter reads the parent; the write only touches the child. With the
    # parent row held by someone else, the write must still claim the child
    # rather than skip it.
    parent = DeleteParent(name="p").create()
    other = DeleteParent(name="other").create()
    ChildCascade(parent=parent).create()

    params = build_connection_params(get_connection().settings_dict)
    with psycopg.connect(**params) as holder:
        with holder.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM \"examples_deleteparent\" WHERE name = 'p' FOR UPDATE"
            )
            assert cursor.fetchall()

            qs = ChildCascade.query.filter(parent__name="p").for_update(
                skip_locked=True
            )
            with transaction.atomic():
                claimed = qs.update(parent=other) if write == "update" else qs.delete()

        holder.rollback()

    assert claimed == 1

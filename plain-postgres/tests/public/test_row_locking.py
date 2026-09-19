"""
Row-level locking: for_update(), for_no_key_update(), for_share(), and
for_key_share() emit the matching Postgres locking clause and options.
"""

from __future__ import annotations

import re

import pytest
from app.examples.models.relationships import Widget
from plain.postgres import transaction
from plain.postgres.aggregates import Count
from plain.postgres.expressions import Value, Window
from plain.postgres.functions import RowNumber
from plain.postgres.transaction import TransactionManagementError
from psycopg import NotSupportedError


def _executed_sql(queries: list[dict]) -> str:
    return " ".join(q["sql"] for q in queries)


@pytest.mark.parametrize(
    ("method", "clause"),
    [
        ("for_update", "FOR UPDATE"),
        ("for_no_key_update", "FOR NO KEY UPDATE"),
        ("for_share", "FOR SHARE"),
        ("for_key_share", "FOR KEY SHARE"),
    ],
)
def test_lock_method_emits_its_clause(db, capture_queries, method, clause):
    with capture_queries() as queries:
        list(getattr(Widget.query, method)())
    assert clause in _executed_sql(queries)


def test_nowait_appends_nowait(db, capture_queries):
    with capture_queries() as queries:
        list(Widget.query.for_update(nowait=True))
    assert "FOR UPDATE NOWAIT" in _executed_sql(queries)


def test_skip_locked_appends_skip_locked(db, capture_queries):
    with capture_queries() as queries:
        list(Widget.query.for_share(skip_locked=True))
    assert "FOR SHARE SKIP LOCKED" in _executed_sql(queries)


def test_of_restricts_lock_to_named_table(db, capture_queries):
    with capture_queries() as queries:
        list(Widget.query.for_update(of=("self",)))
    assert "FOR UPDATE OF" in _executed_sql(queries)


def test_nowait_and_skip_locked_together_raise():
    with pytest.raises(ValueError, match="nowait"):
        Widget.query.for_update(nowait=True, skip_locked=True)


def test_last_lock_mode_wins(db, capture_queries):
    with capture_queries() as queries:
        list(Widget.query.for_update().for_share())
    sql = _executed_sql(queries)
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


def test_non_aggregate_annotation_is_allowed_with_a_lock(db, capture_queries):
    # Only aggregation forces a GROUP BY; a plain expression annotation leaves
    # the rows mapping one-to-one onto table rows, so Postgres can lock them.
    with capture_queries() as queries:
        list(Widget.query.for_update().annotate(label=Value("x")))
    assert "FOR UPDATE" in _executed_sql(queries)


def test_lock_after_window_annotation_raises(db):
    with pytest.raises(NotSupportedError, match="window annotation"):
        Widget.query.annotate(rn=Window(RowNumber())).for_update()


def test_window_annotation_after_lock_raises(db):
    with pytest.raises(NotSupportedError, match="window annotation"):
        Widget.query.for_update().annotate(rn=Window(RowNumber()))


def test_count_and_aggregate_still_drop_the_lock(db, capture_queries):
    # Unchanged by the up-front guards: both compile to an aggregate query of
    # their own, so the lock is dropped rather than rejected.
    with capture_queries() as queries:
        assert Widget.query.for_update().count() == 0
    assert "FOR UPDATE" not in _executed_sql(queries)

    with capture_queries() as queries:
        assert Widget.query.for_update().aggregate(n=Count("id")) == {"n": 0}
    assert "FOR UPDATE" not in _executed_sql(queries)


# ---------------------------------------------------------------------------
# Set-based writes
#
# Neither UPDATE nor DELETE takes a locking clause, so the lock has to move
# onto the sub-select that picks the rows rather than being dropped.
# ---------------------------------------------------------------------------


def test_locked_update_locks_in_a_subquery(db, capture_queries):
    with capture_queries() as queries:
        Widget.query.for_update(skip_locked=True).update(name="x")

    sql = _executed_sql(queries)
    assert "IN (SELECT" in sql
    assert "FOR UPDATE SKIP LOCKED)" in sql


def test_locked_delete_locks_in_a_subquery(db, capture_queries):
    with capture_queries() as queries:
        Widget.query.for_update(skip_locked=True).delete()

    sql = _executed_sql(queries)
    assert "IN (SELECT" in sql
    assert "FOR UPDATE SKIP LOCKED)" in sql


def test_unlocked_writes_stay_a_flat_statement(db, capture_queries):
    with capture_queries() as queries:
        Widget.query.update(name="x")

    assert "IN (SELECT" not in _executed_sql(queries)

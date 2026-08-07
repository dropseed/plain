"""
Row-level locking: for_update(), for_no_key_update(), for_share(), and
for_key_share() emit the matching Postgres locking clause and options.
"""

from __future__ import annotations

import pytest
from app.examples.models.relationships import Widget

from plain.postgres import transaction
from plain.postgres.transaction import TransactionManagementError


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
    with pytest.raises(TransactionManagementError):
        list(Widget.query.for_update())


def test_lock_works_inside_atomic(isolated_db):
    Widget.query.create(name="W", size="L")
    with transaction.atomic():
        widgets = list(Widget.query.for_update())
    assert len(widgets) == 1

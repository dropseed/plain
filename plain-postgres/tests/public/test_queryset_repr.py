from __future__ import annotations

from app.examples.models.iteration import IterationExample


def test_repr_does_not_execute_sql_when_unevaluated(db, capture_queries):
    """repr() of an unevaluated queryset must not issue a SQL query.

    Error reporters (Sentry, pdb, exception templates) call repr() on
    stack-frame locals; a surprise SELECT inside an exception path can
    overload the database.
    """
    qs = IterationExample.query.all()

    with capture_queries() as queries:
        repr(qs)

    assert queries == []
    assert repr(qs) == "<QuerySet [unevaluated]>"


def test_repr_uses_cache_when_evaluated(db, capture_queries):
    """Once a queryset is evaluated, repr() reflects its rows without re-querying."""
    IterationExample.query.create(name="alpha", tag="a")
    IterationExample.query.create(name="beta", tag="b")

    qs = IterationExample.query.all()
    list(qs)  # force evaluation, populates _result_cache

    with capture_queries() as queries:
        repr(qs)

    assert queries == []
    rendered = repr(qs)
    assert "[unevaluated]" not in rendered
    assert rendered.count("IterationExample") == 2


def test_repr_truncates_large_evaluated_querysets(db):
    """The truncation marker still appears past REPR_OUTPUT_SIZE."""
    for i in range(25):
        IterationExample.query.create(name=f"name{i:02d}", tag="t")

    qs = IterationExample.query.all()
    list(qs)

    rendered = repr(qs)
    assert "remaining elements truncated" in rendered

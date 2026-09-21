"""The typed terminal entry points are sugar, not a second query builder.

Each spelling has to compile to the same statement the long form does --
otherwise converting a call site would change the SQL text, which a pinned
statement test notices and so does `pg_stat_statements`, which groups by
structure rather than literal text.

The behavioral contract lives in `tests/public/test_typed_get.py`.
"""

from __future__ import annotations

from app.examples.models.defaults import DefaultsExample


def statement_for(build, capture_queries):
    with capture_queries() as queries:
        build()
    return [q["sql"] for q in queries]


def test_primary_key_form_matches_the_long_form(db, capture_queries):
    by_key = statement_for(
        lambda: DefaultsExample.query.get_or_none(5), capture_queries
    )
    by_condition = statement_for(
        lambda: DefaultsExample.query.where(DefaultsExample.id.equals(5)).get_or_none(),
        capture_queries,
    )
    by_kwarg = statement_for(
        lambda: DefaultsExample.query.get_or_none(id=5), capture_queries
    )

    assert by_key == by_condition == by_kwarg
    assert len(by_key) == 1


def test_conditions_match_the_long_form(db, capture_queries):
    conditions = (
        DefaultsExample.name.equals("alice"),
        DefaultsExample.priority.gte(5),
    )

    inline = statement_for(
        lambda: DefaultsExample.query.get_or_none(*conditions), capture_queries
    )
    chained = statement_for(
        lambda: DefaultsExample.query.where(*conditions).get_or_none(), capture_queries
    )

    assert inline == chained


def test_first_matches_the_long_form(db, capture_queries):
    condition = DefaultsExample.name.equals("alice")

    inline = statement_for(
        lambda: DefaultsExample.query.first(condition), capture_queries
    )
    chained = statement_for(
        lambda: DefaultsExample.query.where(condition).first(), capture_queries
    )

    assert inline == chained


def test_last_matches_the_long_form(db, capture_queries):
    condition = DefaultsExample.name.equals("alice")

    inline = statement_for(
        lambda: DefaultsExample.query.last(condition), capture_queries
    )
    chained = statement_for(
        lambda: DefaultsExample.query.where(condition).last(), capture_queries
    )

    assert inline == chained


def test_no_argument_terminals_are_untouched(db, capture_queries):
    """`first()`/`last()` with no conditions run the query they always ran."""
    ordered = DefaultsExample.query.order_by("priority")

    with capture_queries() as first_queries:
        ordered.first()
    with capture_queries() as sliced_queries:
        list(ordered[:1])

    assert [q["sql"] for q in first_queries] == [q["sql"] for q in sliced_queries]

"""Static claims for `Model.query.sql()`.

The template is a `Template` — a t-string and nothing else. A `str`, however
it was written, is not one, so the type is the rule and there is no
source-reading lint. What the type buys is that no string reaches `sql()` by
accident; hand-building a `Template` out of one is still possible, and is the
thing never to do with text from outside the program.

`{Model:*}` hands back the model; `result_type=` hands back the dataclass; a
`result_type` that isn't a dataclass is a type error, not just a runtime one.
The runtime half is in tests/public/test_written_sql.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import assert_type

from app.examples.models.relationships import Widget
from plain.postgres import Written

# A shared predicate is an ordinary module-level t-string.
SMALL = t"{Widget.size} = 'small'"


@dataclass
class SizeCount:
    size: str
    n: int


def star_statements_yield_instances() -> None:
    statement = Widget.query.sql(t"SELECT {Widget:*} FROM {Widget}")
    assert_type(statement, Written[Widget])
    assert_type(statement.all(), list[Widget])
    assert_type(statement.first(), Widget | None)
    assert_type(statement.get(), Widget)


def prefetch_keeps_the_statement_type() -> None:
    statement = Widget.query.sql(t"SELECT {Widget:*} FROM {Widget}").prefetch("tags")
    assert_type(statement, Written[Widget])


def result_type_statements_yield_rows() -> None:
    statement = Widget.query.sql(
        t"SELECT {Widget.size} AS size, count(*) AS n FROM {Widget} GROUP BY 1",
        result_type=SizeCount,
    )
    assert_type(statement, Written[SizeCount])
    assert_type(statement.all(), list[SizeCount])
    assert_type(statement.first(), SizeCount | None)
    for row in statement:
        assert_type(row, SizeCount)


def a_module_level_template_is_a_template() -> None:
    """A shared t-string is a value like any other — no literal rule to break."""
    statement = Widget.query.sql(t"SELECT {Widget:*} FROM {Widget} WHERE {SMALL}")
    assert_type(statement, Written[Widget])


def a_string_is_not_a_template() -> None:
    """The runtime half is tests/public/test_written_sql.py."""
    Widget.query.sql("SELECT {Widget:*} FROM {Widget}")  # ty: ignore[invalid-argument-type]


def an_f_string_is_not_a_template() -> None:
    table = "widgets"
    Widget.query.sql(f"SELECT * FROM {table}")  # ty: ignore[invalid-argument-type]


def a_built_string_is_not_a_template() -> None:
    table = "widgets"
    Widget.query.sql("SELECT * FROM " + table)  # ty: ignore[invalid-argument-type]


def values_are_not_passed_by_keyword() -> None:
    """The t-string carries its values; `sql()` has no `**values`."""
    Widget.query.sql(  # ty: ignore[no-matching-overload]
        t"SELECT {Widget:*} FROM {Widget}",
        size="small",
    )


def a_result_type_has_to_be_a_dataclass() -> None:
    Widget.query.sql(  # ty: ignore[no-matching-overload]
        t"SELECT count(*) AS n FROM {Widget}",
        result_type=int,
    )

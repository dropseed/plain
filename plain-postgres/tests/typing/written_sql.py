"""Static claims for `Model.query.sql()`.

`{Model.*}` hands back the model; `result_type=` hands back the dataclass; a
`result_type` that isn't a dataclass is a type error, not just a runtime one.
The runtime half is in tests/public/test_written_sql.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import assert_type

from app.examples.models.relationships import Widget
from plain.postgres import Written


@dataclass
class SizeCount:
    size: str
    n: int


def star_statements_yield_instances() -> None:
    statement = Widget.query.sql("SELECT {Widget.*} FROM {Widget}")
    assert_type(statement, Written[Widget])
    assert_type(statement.all(), list[Widget])
    assert_type(statement.first(), Widget | None)
    assert_type(statement.get(), Widget)


def prefetch_keeps_the_statement_type() -> None:
    statement = Widget.query.sql("SELECT {Widget.*} FROM {Widget}").prefetch("tags")
    assert_type(statement, Written[Widget])


def result_type_statements_yield_rows() -> None:
    statement = Widget.query.sql(
        "SELECT {Widget.size} AS size, count(*) AS n FROM {Widget} GROUP BY 1",
        result_type=SizeCount,
    )
    assert_type(statement, Written[SizeCount])
    assert_type(statement.all(), list[SizeCount])
    assert_type(statement.first(), SizeCount | None)
    for row in statement:
        assert_type(row, SizeCount)


def a_result_type_has_to_be_a_dataclass() -> None:
    Widget.query.sql(  # ty: ignore[no-matching-overload]
        "SELECT count(*) AS n FROM {Widget}",
        result_type=int,
    )

"""Invariants the returning() write path depends on internally.

These poke private state directly: they pin the contracts between the
queryset, the query and the compiler, not anything a user calls.
"""

from __future__ import annotations

import typing

import pytest
from app.examples.models.returning import ReturningEvent
from plain.postgres.exceptions import FieldError
from plain.postgres.query import QuerySet
from plain.postgres.sql.constants import CURSOR, MULTI, NO_RESULTS, SINGLE
from plain.postgres.sql.query import UpdateQuery


def test_returning_annotations_resolve_at_runtime():
    # ReturningQuerySet is a static-only name, but returning()'s annotations
    # mention it and annotations get evaluated -- get_type_hints() and doc
    # generators walk them. (The type parameters have to be supplied by hand
    # for any PEP 695 generic method; QuerySet.create has the same need.)
    type_params = {tp.__name__: tp for tp in QuerySet.__type_params__}
    hints = typing.get_type_hints(QuerySet.returning, localns=type_params)

    assert "return" in hints


def test_returning_rejects_an_empty_selection(db):
    # The write path reads "no returning()" off `_returning_fields is None`,
    # so an empty list would emit no RETURNING clause and then try to read
    # rows back from it. It has to be refused where it is built.
    with pytest.raises(FieldError, match="at least one column"):
        ReturningEvent.query._validated_returning_fields(())


def _update_query() -> UpdateQuery:
    query = ReturningEvent.query.sql_query.chain(UpdateQuery)
    query.add_update_values({"count": 1})
    return query


@pytest.mark.parametrize("result_type", [MULTI, SINGLE])
def test_write_compiler_rejects_row_shaping_result_types(db, result_type):
    # A write has a rowcount or its RETURNING rows, never a result set --
    # asking for one used to surface as a psycopg "didn't produce records"
    # several frames away.
    with pytest.raises(AssertionError, match="CURSOR or NO_RESULTS"):
        _update_query().get_compiler().execute_sql(result_type)


@pytest.mark.parametrize("result_type", [CURSOR, NO_RESULTS])
def test_write_compiler_accepts_the_write_result_types(db, result_type):
    # NO_RESULTS is what UpdateQuery.update_batch uses.
    assert _update_query().get_compiler().execute_sql(result_type) == 0

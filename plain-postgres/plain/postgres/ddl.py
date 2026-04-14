"""
DDL generation helpers for convergence and schema management.

Higher-level SQL builders that need database connections, ORM query machinery,
and constraint/index types. Separated from dialect.py (which is low-level and
imported everywhere) to avoid circular imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import psycopg.sql

from plain.postgres.db import get_connection
from plain.postgres.dialect import quote_name
from plain.postgres.expressions import ExpressionList
from plain.postgres.query_utils import Q
from plain.postgres.sql.query import Query

if TYPE_CHECKING:
    from plain.postgres.base import Model
    from plain.postgres.constraints import Deferrable


def quote_value(value: Any) -> str:
    """Quote a value for safe inclusion in a SQL string.

    Not safe against injection from user code — intended only for SQL scripts,
    default values, and constraint expressions (which are not user-defined).
    """
    if isinstance(value, str):
        value = value.replace("%", "%%")
    conn = get_connection()
    return psycopg.sql.quote(value, conn.connection)


def deferrable_sql(deferrable: Deferrable | None) -> str:
    """Return the DEFERRABLE clause for a constraint, or empty string."""
    from plain.postgres.constraints import (
        Deferrable,  # circular: constraints imports ddl
    )

    if deferrable is None:
        return ""
    if deferrable == Deferrable.DEFERRED:
        return " DEFERRABLE INITIALLY DEFERRED"
    if deferrable == Deferrable.IMMEDIATE:
        return " DEFERRABLE INITIALLY IMMEDIATE"
    return ""


def compile_expression_sql(model: type[Model], expression_q: Q) -> str:
    """Compile a Q expression to a SQL string with quoted literal params."""
    query = Query(model=model, alias_cols=False)
    where = query.build_where(expression_q)
    compiler = query.get_compiler()
    conn = get_connection()
    sql, params = where.as_sql(compiler, conn)
    return sql % tuple(quote_value(p) for p in params)


def compile_database_default_sql(expression: Any) -> str:
    """Compile a DatabaseDefaultExpression to parameter-free DDL SQL."""
    compiler = Query(None).get_compiler()
    conn = get_connection()
    sql, params = expression.as_sql(compiler, conn)
    if params:
        raise ValueError(
            f"Expression defaults must compile to parameter-free SQL; "
            f"got params={params!r} for {expression!r}."
        )
    return sql


def compile_index_expressions_sql(
    model: type[Model], expressions: tuple[Any, ...]
) -> str:
    """Compile index/constraint expressions (e.g. F(), OrderBy) to SQL."""
    from plain.postgres.indexes import IndexExpression  # circular: indexes imports ddl

    query = Query(model, alias_cols=False)
    compiler = query.get_compiler()
    index_expressions = [IndexExpression(expr) for expr in expressions]
    expr_list = ExpressionList(*index_expressions).resolve_expression(query)
    sql, params = compiler.compile(expr_list)
    return sql % tuple(quote_value(p) for p in params)


def build_include_sql(model: type[Model], include: tuple[str, ...]) -> str:
    """Build the INCLUDE clause for an index or constraint, or empty string."""
    if not include:
        return ""
    include_cols = [
        quote_name(model._model_meta.get_forward_field(f).column) for f in include
    ]
    return " INCLUDE ({})".format(", ".join(include_cols))

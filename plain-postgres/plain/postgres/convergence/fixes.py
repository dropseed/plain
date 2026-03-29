from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..constraints import BaseConstraint, CheckConstraint
from ..db import get_connection
from ..dialect import quote_name
from ..indexes import Index


def _execute_and_commit(sql: str) -> None:
    """Execute SQL and commit. Rolls back on failure so the connection stays usable."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _execute_autocommit(sql: str) -> None:
    """Execute SQL in autocommit mode (required for CONCURRENTLY operations)."""
    conn = get_connection()
    conn.set_autocommit(True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
    finally:
        conn.set_autocommit(False)


@dataclass
class RebuildIndexFix:
    """Drop an INVALID index and recreate it CONCURRENTLY."""

    pass_order = 0

    table: str
    index: Index
    model: Any
    name: str

    def describe(self) -> str:
        return f"{self.table}: rebuild invalid index {self.name}"

    def apply(self) -> str:
        conn = get_connection()
        # Drop the invalid index first
        drop_sql = f"DROP INDEX CONCURRENTLY IF EXISTS {quote_name(self.name)}"
        _execute_autocommit(drop_sql)
        # Recreate it
        with conn.schema_editor(collect_sql=True) as editor:
            create_sql = self.index.create_sql(self.model, editor, concurrently=True)
        create_sql_str = str(create_sql)
        _execute_autocommit(create_sql_str)
        return f"{drop_sql}; {create_sql_str}"


@dataclass
class CreateIndexFix:
    """Create a missing index using CONCURRENTLY (doesn't block writes)."""

    pass_order = 1

    table: str
    index: Index
    model: Any

    def describe(self) -> str:
        return f"{self.table}: create index {self.index.name}"

    def apply(self) -> str:
        conn = get_connection()
        with conn.schema_editor(collect_sql=True) as editor:
            sql = self.index.create_sql(self.model, editor, concurrently=True)
        sql_str = str(sql)
        _execute_autocommit(sql_str)
        return sql_str


@dataclass
class AddConstraintFix:
    """Add a missing constraint using NOT VALID for check constraints."""

    pass_order = 2

    table: str
    constraint: BaseConstraint
    model: Any

    def describe(self) -> str:
        suffix = " (NOT VALID)" if isinstance(self.constraint, CheckConstraint) else ""
        return f"{self.table}: add constraint {self.constraint.name}{suffix}"

    def apply(self) -> str:
        conn = get_connection()
        with conn.schema_editor(collect_sql=True) as editor:
            sql = self.constraint.create_sql(self.model, editor)
        sql_str = str(sql)

        if isinstance(self.constraint, CheckConstraint):
            sql_str += " NOT VALID"

        _execute_and_commit(sql_str)
        return sql_str


@dataclass
class ValidateConstraintFix:
    """Validate a NOT VALID constraint (SHARE UPDATE EXCLUSIVE — doesn't block writes)."""

    pass_order = 3

    table: str
    name: str

    def describe(self) -> str:
        return f"{self.table}: validate constraint {self.name}"

    def apply(self) -> str:
        sql = f"ALTER TABLE {quote_name(self.table)} VALIDATE CONSTRAINT {quote_name(self.name)}"
        _execute_and_commit(sql)
        return sql


@dataclass
class DropConstraintFix:
    pass_order = 4

    table: str
    name: str

    def describe(self) -> str:
        return f"{self.table}: drop constraint {self.name}"

    def apply(self) -> str:
        sql = f"ALTER TABLE {quote_name(self.table)} DROP CONSTRAINT {quote_name(self.name)}"
        _execute_and_commit(sql)
        return sql


@dataclass
class DropIndexFix:
    pass_order = 5

    table: str
    name: str

    def describe(self) -> str:
        return f"{self.table}: drop index {self.name}"

    def apply(self) -> str:
        sql = f"DROP INDEX CONCURRENTLY IF EXISTS {quote_name(self.name)}"
        _execute_autocommit(sql)
        return sql


Fix = (
    RebuildIndexFix
    | CreateIndexFix
    | AddConstraintFix
    | ValidateConstraintFix
    | DropConstraintFix
    | DropIndexFix
)

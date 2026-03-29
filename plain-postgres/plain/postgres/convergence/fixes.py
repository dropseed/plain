from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from ..constraints import BaseConstraint, CheckConstraint, UniqueConstraint
from ..db import get_connection
from ..dialect import quote_name
from ..indexes import Index

if TYPE_CHECKING:
    from ..base import Model


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
    """Execute SQL in autocommit mode (required for CONCURRENTLY operations).

    Commits any pending transaction first, since Postgres doesn't allow
    switching to autocommit while a transaction is active.
    """
    conn = get_connection()
    if conn.in_atomic_block:
        raise RuntimeError("Cannot use CONCURRENTLY inside an atomic block")
    old_autocommit = conn.get_autocommit()
    if not old_autocommit:
        conn.commit()
        conn.set_autocommit(True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
    finally:
        if not old_autocommit:
            conn.set_autocommit(False)


class Fix(ABC):
    """Concrete executable SQL operation for convergence."""

    pass_order: ClassVar[int]

    @abstractmethod
    def describe(self) -> str: ...

    @abstractmethod
    def apply(self) -> str: ...


@dataclass
class RebuildIndexFix(Fix):
    """Drop an INVALID index and recreate it CONCURRENTLY."""

    pass_order = 0

    table: str
    index: Index
    model: type[Model]

    def describe(self) -> str:
        return f"{self.table}: rebuild index {self.index.name}"

    def apply(self) -> str:
        drop_sql = f"DROP INDEX CONCURRENTLY IF EXISTS {quote_name(self.index.name)}"
        _execute_autocommit(drop_sql)
        create_sql = self.index.to_sql(self.model)
        _execute_autocommit(create_sql)
        return f"{drop_sql}; {create_sql}"


@dataclass
class RenameIndexFix(Fix):
    """Rename an index (catalog-only, instant)."""

    pass_order = 1

    table: str
    old_name: str
    new_name: str

    def describe(self) -> str:
        return f"{self.table}: rename index {self.old_name} -> {self.new_name}"

    def apply(self) -> str:
        sql = f"ALTER INDEX {quote_name(self.old_name)} RENAME TO {quote_name(self.new_name)}"
        _execute_and_commit(sql)
        return sql


@dataclass
class CreateIndexFix(Fix):
    """Create a missing index using CONCURRENTLY (doesn't block writes)."""

    pass_order = 1

    table: str
    index: Index
    model: type[Model]

    def describe(self) -> str:
        return f"{self.table}: create index {self.index.name}"

    def apply(self) -> str:
        sql = self.index.to_sql(self.model)
        _execute_autocommit(sql)
        return sql


@dataclass
class AddConstraintFix(Fix):
    """Add a missing constraint.

    Check constraints use NOT VALID to avoid a table scan.
    Unique constraints use CREATE UNIQUE INDEX CONCURRENTLY + USING INDEX
    to avoid blocking writes.
    """

    pass_order = 2

    table: str
    constraint: BaseConstraint
    model: type[Model]

    def describe(self) -> str:
        if isinstance(self.constraint, CheckConstraint):
            return f"{self.table}: add constraint {self.constraint.name} (NOT VALID)"
        return f"{self.table}: add constraint {self.constraint.name}"

    def apply(self) -> str:
        if isinstance(self.constraint, UniqueConstraint):
            return self._apply_unique()
        return self._apply_other()

    def _apply_unique(self) -> str:
        assert isinstance(self.constraint, UniqueConstraint)

        # Step 1: Create unique index concurrently (non-blocking, handles all
        # UniqueConstraint features: condition, include, opclasses, expressions)
        create_idx = self.constraint.to_sql(self.model, concurrently=True)
        _execute_autocommit(create_idx)

        # Step 2: Attach as constraint using the index (instant)
        add_constraint = self.constraint.to_attach_sql(self.model)
        try:
            _execute_and_commit(add_constraint)
        except Exception:
            # Clean up the orphaned index if the constraint attachment fails
            name = quote_name(self.constraint.name)
            _execute_autocommit(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
            raise

        return f"{create_idx}; {add_constraint}"

    def _apply_other(self) -> str:
        if isinstance(self.constraint, CheckConstraint):
            sql = self.constraint.to_sql(self.model, not_valid=True)
        else:
            sql = self.constraint.to_sql(self.model)
        _execute_and_commit(sql)
        return sql


@dataclass
class RenameConstraintFix(Fix):
    """Rename a constraint (catalog-only, instant).

    For unique constraints, Postgres automatically renames the backing index.
    """

    pass_order = 2

    table: str
    old_name: str
    new_name: str

    def describe(self) -> str:
        return f"{self.table}: rename constraint {self.old_name} -> {self.new_name}"

    def apply(self) -> str:
        sql = f"ALTER TABLE {quote_name(self.table)} RENAME CONSTRAINT {quote_name(self.old_name)} TO {quote_name(self.new_name)}"
        _execute_and_commit(sql)
        return sql


@dataclass
class ValidateConstraintFix(Fix):
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
class DropConstraintFix(Fix):
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
class DropIndexFix(Fix):
    pass_order = 5

    table: str
    name: str

    def describe(self) -> str:
        return f"{self.table}: drop index {self.name}"

    def apply(self) -> str:
        sql = f"DROP INDEX CONCURRENTLY IF EXISTS {quote_name(self.name)}"
        _execute_autocommit(sql)
        return sql

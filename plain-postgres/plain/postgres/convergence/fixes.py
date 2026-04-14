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

        # Step 1: Create unique index concurrently (non-blocking)
        create_idx = self.constraint.to_sql(self.model, concurrently=True)
        _execute_autocommit(create_idx)

        # Step 2: Attach as constraint — but only for variants PostgreSQL
        # accepts.  Partial indexes, expression indexes, and non-default
        # operator class indexes cannot be attached as constraints; they
        # remain as unique indexes (same enforcement, no pg_constraint row).
        if self.constraint.index_only:
            return create_idx

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
class AddForeignKeyFix(Fix):
    """Add a missing FK constraint using NOT VALID, then validate immediately.

    Step 1: ADD CONSTRAINT ... NOT VALID (SHARE ROW EXCLUSIVE, no scan)
    Step 2: VALIDATE CONSTRAINT (SHARE UPDATE EXCLUSIVE, scans data)

    Both steps run in a single apply() because the validate lock is weaker
    than the add lock — there's no benefit to deferring validation.
    """

    pass_order = 2

    table: str
    constraint_name: str
    column: str
    target_table: str
    target_column: str
    on_delete_clause: str = ""  # e.g. " ON DELETE CASCADE" or "" for NO ACTION

    def describe(self) -> str:
        return f"{self.table}: add FK {self.constraint_name} ({self.column} → {self.target_table}.{self.target_column})"

    def apply(self) -> str:
        add_sql = (
            f"ALTER TABLE {quote_name(self.table)}"
            f" ADD CONSTRAINT {quote_name(self.constraint_name)}"
            f" FOREIGN KEY ({quote_name(self.column)})"
            f" REFERENCES {quote_name(self.target_table)} ({quote_name(self.target_column)})"
            f"{self.on_delete_clause}"
            f" DEFERRABLE INITIALLY DEFERRED"
            f" NOT VALID"
        )
        _execute_and_commit(add_sql)

        validate_sql = (
            f"ALTER TABLE {quote_name(self.table)}"
            f" VALIDATE CONSTRAINT {quote_name(self.constraint_name)}"
        )
        _execute_and_commit(validate_sql)

        return f"{add_sql}; {validate_sql}"


@dataclass
class ReplaceForeignKeyFix(Fix):
    """Swap a FK's ON DELETE action, then validate.

    Step 1: ALTER TABLE DROP CONSTRAINT + ADD CONSTRAINT ... NOT VALID
            (ACCESS EXCLUSIVE on the referenced table's DROP, but the
            statement is catalog-only — no table scan)
    Step 2: VALIDATE CONSTRAINT (SHARE UPDATE EXCLUSIVE, scans data)

    Between steps the constraint exists as NOT VALID, which still enforces
    on new inserts/updates — so there is no window of unsafe writes. The
    DROP and ADD share a single ALTER TABLE statement so the old
    constraint is never absent in the catalog.

    VALIDATE still scans the table, but under a weaker lock than a naive
    DROP + ADD would take for the validation scan. Existing rows were
    already valid under the previous constraint (on_delete action doesn't
    affect what is validated — only what happens at delete time), so
    the scan will pass unless the data was corrupted out-of-band.
    """

    pass_order = 2

    table: str
    constraint_name: str
    column: str
    target_table: str
    target_column: str
    on_delete_clause: str

    def describe(self) -> str:
        return f"{self.table}: update FK {self.constraint_name} on_delete"

    def apply(self) -> str:
        replace_sql = (
            f"ALTER TABLE {quote_name(self.table)}"
            f" DROP CONSTRAINT {quote_name(self.constraint_name)},"
            f" ADD CONSTRAINT {quote_name(self.constraint_name)}"
            f" FOREIGN KEY ({quote_name(self.column)})"
            f" REFERENCES {quote_name(self.target_table)} ({quote_name(self.target_column)})"
            f"{self.on_delete_clause}"
            f" DEFERRABLE INITIALLY DEFERRED"
            f" NOT VALID"
        )
        _execute_and_commit(replace_sql)

        validate_sql = (
            f"ALTER TABLE {quote_name(self.table)}"
            f" VALIDATE CONSTRAINT {quote_name(self.constraint_name)}"
        )
        _execute_and_commit(validate_sql)

        return f"{replace_sql}; {validate_sql}"


@dataclass
class SetNotNullFix(Fix):
    """Enforce NOT NULL via CHECK NOT VALID → VALIDATE → SET NOT NULL.

    A bare SET NOT NULL acquires ACCESS EXCLUSIVE and scans the whole table
    while holding it.  With a validated IS NOT NULL check constraint already
    in place, Postgres (12+) skips the scan and the lock is brief.

    Transaction boundaries are chosen to keep lock windows narrow:

      1. ADD CHECK (col IS NOT NULL) NOT VALID  — catalog-only, brief lock
      2. VALIDATE CONSTRAINT                    — SHARE UPDATE EXCLUSIVE scan
      3. SET NOT NULL + DROP temp check          — atomic, instant catalog ops

    Steps 3+4 share a single commit so no orphaned temp check can remain
    after the column becomes NOT NULL.  If earlier steps fail, the leftover
    temp check is cleaned up at the start of the next run (analysis also
    ignores framework-owned temp checks so they never block sync).
    """

    pass_order = 2

    table: str
    column: str

    def describe(self) -> str:
        return f"{self.table}: set NOT NULL on {self.column}"

    def apply(self) -> str:
        from .analysis import generate_notnull_check_name

        t = quote_name(self.table)
        c = quote_name(self.column)
        check = quote_name(generate_notnull_check_name(self.table, self.column))

        # Clean up any leftover temp constraint from a previous failed run
        _execute_and_commit(f"ALTER TABLE {t} DROP CONSTRAINT IF EXISTS {check}")

        # Step 1: Add NOT VALID check (no scan, brief lock)
        add_sql = (
            f"ALTER TABLE {t} ADD CONSTRAINT {check} CHECK ({c} IS NOT NULL) NOT VALID"
        )
        _execute_and_commit(add_sql)

        # Step 2: Validate (SHARE UPDATE EXCLUSIVE — non-blocking scan)
        validate_sql = f"ALTER TABLE {t} VALIDATE CONSTRAINT {check}"
        _execute_and_commit(validate_sql)

        # Step 3: SET NOT NULL + drop temp check in one commit.
        # Both are instant catalog operations (SET NOT NULL skips the scan
        # thanks to the validated check).  Combining them ensures no orphaned
        # temp check if SET NOT NULL succeeds.
        set_sql = f"ALTER TABLE {t} ALTER COLUMN {c} SET NOT NULL"
        drop_sql = f"ALTER TABLE {t} DROP CONSTRAINT {check}"
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(set_sql)
                cursor.execute(drop_sql)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        return f"{add_sql}; {validate_sql}; {set_sql}; {drop_sql}"


@dataclass
class DropNotNullFix(Fix):
    """Remove NOT NULL from a column (model now allows NULL).

    DROP NOT NULL is a catalog-only change — no data scan, instant.
    """

    pass_order = 2

    table: str
    column: str

    def describe(self) -> str:
        return f"{self.table}: drop NOT NULL on {self.column}"

    def apply(self) -> str:
        sql = f"ALTER TABLE {quote_name(self.table)} ALTER COLUMN {quote_name(self.column)} DROP NOT NULL"
        _execute_and_commit(sql)
        return sql


@dataclass
class SetColumnDefaultFix(Fix):
    """Set (or replace) a column's DEFAULT (catalog-only, instant)."""

    pass_order = 2

    table: str
    column: str
    default_sql: str

    def describe(self) -> str:
        return f"{self.table}: set DEFAULT {self.default_sql} on {self.column}"

    def apply(self) -> str:
        sql = (
            f"ALTER TABLE {quote_name(self.table)}"
            f" ALTER COLUMN {quote_name(self.column)}"
            f" SET DEFAULT {self.default_sql}"
        )
        _execute_and_commit(sql)
        return sql


@dataclass
class DropColumnDefaultFix(Fix):
    """Drop a column's DEFAULT (catalog-only, instant)."""

    pass_order = 2

    table: str
    column: str

    def describe(self) -> str:
        return f"{self.table}: drop DEFAULT on {self.column}"

    def apply(self) -> str:
        sql = (
            f"ALTER TABLE {quote_name(self.table)}"
            f" ALTER COLUMN {quote_name(self.column)}"
            f" DROP DEFAULT"
        )
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

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..db import get_connection

if TYPE_CHECKING:
    from ..connection import DatabaseConnection
    from ..utils import CursorWrapper


@dataclass
class ColumnState:
    type: str
    not_null: bool


@dataclass
class IndexState:
    columns: list[str]
    valid: bool


@dataclass
class ConstraintState:
    columns: list[str]
    validated: bool
    definition: str | None = None


@dataclass
class ForeignKeyState:
    column: str
    target_table: str
    target_column: str


@dataclass
class TableState:
    """Raw database state for a single table — no model comparison."""

    exists: bool = True
    columns: dict[str, ColumnState] = field(default_factory=dict)
    indexes: dict[str, IndexState] = field(default_factory=dict)
    check_constraints: dict[str, ConstraintState] = field(default_factory=dict)
    unique_constraints: dict[str, ConstraintState] = field(default_factory=dict)
    foreign_keys: dict[str, ForeignKeyState] = field(default_factory=dict)


def introspect_table(
    conn: DatabaseConnection, cursor: CursorWrapper, table_name: str
) -> TableState:
    """Query the database and return the raw state of a table."""
    actual_columns = _get_columns(cursor, table_name)
    if not actual_columns:
        return TableState(exists=False)

    raw = conn.get_constraints(cursor, table_name)

    indexes: dict[str, IndexState] = {}
    check_constraints: dict[str, ConstraintState] = {}
    unique_constraints: dict[str, ConstraintState] = {}
    foreign_keys: dict[str, ForeignKeyState] = {}

    for name, info in raw.items():
        if info.get("primary_key"):
            continue

        if info.get("unique"):
            unique_constraints[name] = ConstraintState(
                columns=list(info.get("columns") or []),
                validated=info.get("validated", True),
                definition=info.get("definition"),
            )
        elif info.get("check"):
            check_constraints[name] = ConstraintState(
                columns=list(info.get("columns") or []),
                validated=info.get("validated", True),
                definition=info.get("definition"),
            )
        elif info.get("foreign_key"):
            fk_target = info.get("foreign_key", ())
            fk_cols = info.get("columns", [])
            if len(fk_cols) == 1 and len(fk_target) == 2:
                foreign_keys[name] = ForeignKeyState(
                    column=fk_cols[0],
                    target_table=fk_target[0],
                    target_column=fk_target[1],
                )
        elif info.get("index"):
            indexes[name] = IndexState(
                columns=list(info.get("columns") or []),
                valid=info.get("valid", True),
            )

    return TableState(
        exists=True,
        columns=actual_columns,
        indexes=indexes,
        check_constraints=check_constraints,
        unique_constraints=unique_constraints,
        foreign_keys=foreign_keys,
    )


def get_unknown_tables(conn: DatabaseConnection | None = None) -> list[str]:
    """Return sorted list of database tables not managed by any Plain model."""
    from ..migrations.recorder import MIGRATION_TABLE_NAME

    if conn is None:
        conn = get_connection()
    return sorted(
        set(conn.table_names()) - set(conn.plain_table_names()) - {MIGRATION_TABLE_NAME}
    )


def normalize_check_definition(s: str) -> str:
    """Normalize a constraint definition for comparison.

    Strips outer CHECK(...) wrapper, collapses whitespace, removes
    double-quote identifiers, and strips redundant parentheses so that
    minor formatting differences between pg_get_constraintdef output and
    the schema-editor-generated SQL don't cause false positives.
    """
    s = s.strip()
    # Strip outer CHECK(...)
    if s.upper().startswith("CHECK"):
        s = s[5:].strip()
        if s.startswith("(") and s.endswith(")"):
            s = s[1:-1].strip()
    # Remove double-quoted identifiers (pg may or may not quote column names)
    s = s.replace('"', "")
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)
    # Strip outer redundant parens (pg_get_constraintdef often adds an extra layer)
    while s.startswith("(") and s.endswith(")"):
        inner = s[1:-1]
        # Only strip if the parens are balanced (i.e. they truly wrap the whole expr)
        depth = 0
        balanced = True
        for ch in inner:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if depth < 0:
                balanced = False
                break
        if balanced and depth == 0:
            s = inner.strip()
        else:
            break
    return s.lower()


def _get_columns(cursor: CursorWrapper, table_name: str) -> dict[str, ColumnState]:
    """Return {column_name: ColumnState} from the actual DB."""
    cursor.execute(
        """
        SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
        FROM pg_attribute a
        JOIN pg_class c ON a.attrelid = c.oid
        WHERE c.relname = %s AND pg_catalog.pg_table_is_visible(c.oid)
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        [table_name],
    )
    return {
        name: ColumnState(type=type_str, not_null=is_not_null)
        for name, type_str, is_not_null in cursor.fetchall()
    }

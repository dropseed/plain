from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlparse

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
    definition: str | None = None


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
    validated: bool = True


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
                    validated=info.get("validated", True),
                )
        elif info.get("index"):
            indexes[name] = IndexState(
                columns=list(info.get("columns") or []),
                valid=info.get("valid", True),
                definition=info.get("definition"),
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


def _strip_balanced_parens(s: str) -> str:
    """Strip redundant outermost parentheses when they wrap the entire expression."""
    while s.startswith("(") and s.endswith(")"):
        inner = s[1:-1]
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
    return s


def _normalize_sql(s: str) -> str:
    """Lowercase keywords/identifiers, strip quotes, collapse whitespace."""
    s = sqlparse.format(
        s, keyword_case="lower", identifier_case="lower", strip_whitespace=True
    )
    s = s.replace('"', "")
    return re.sub(r"\s+", " ", s).strip()


def normalize_check_definition(s: str) -> str:
    """Normalize a CHECK constraint definition for comparison.

    Strips the CHECK(...) wrapper and redundant parentheses so that
    pg_get_constraintdef output and model-generated SQL can be compared.
    """
    s = _normalize_sql(s)
    # Strip outer check(...)
    if s.startswith("check"):
        s = s[5:].strip()
        if s.startswith("(") and s.endswith(")"):
            s = s[1:-1].strip()
    s = _strip_balanced_parens(s)
    return s


def normalize_index_definition(s: str) -> str:
    """Extract and normalize the expression part of a CREATE INDEX definition.

    Strips the CREATE INDEX ... ON table [USING method] prefix, leaving just
    the expression spec so that pg_get_indexdef output and model-generated SQL
    can be compared.

    Example: 'CREATE INDEX foo ON bar USING btree (upper(email))'
           → '(upper(email))'
    """
    s = _normalize_sql(s)
    # Strip prefix: find USING <method> or fall back to first ( after ON
    m = re.search(r"\busing \w+ ", s)
    if m:
        s = s[m.end() :]
    else:
        on_pos = s.find(" on ")
        if on_pos >= 0:
            paren = s.find("(", on_pos)
            if paren >= 0:
                s = s[paren:]
    # Strip redundant outer parens — model may generate ((UPPER(col)))
    # while DB has (upper(col))
    s = _strip_balanced_parens(s)
    return s


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

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

import sqlparse

from ..db import get_connection
from ..indexes import Index

if TYPE_CHECKING:
    from ..connection import DatabaseConnection
    from ..utils import CursorWrapper

DEFAULT_INDEX_ACCESS_METHOD = "btree"

# Index access methods that convergence can create and manage.
# Expand when support for new index types ships (e.g. "gin", "gist").
MANAGED_INDEX_ACCESS_METHODS: frozenset[str] = frozenset({DEFAULT_INDEX_ACCESS_METHOD})


class ConType(StrEnum):
    """Postgres pg_constraint.contype values."""

    PRIMARY = "p"
    UNIQUE = "u"
    CHECK = "c"
    FOREIGN_KEY = "f"
    EXCLUSION = "x"

    @property
    def label(self) -> str:
        return _CONTYPE_LABELS[self]


_CONTYPE_LABELS: dict[ConType, str] = {
    ConType.PRIMARY: "primary key",
    ConType.UNIQUE: "unique",
    ConType.CHECK: "check",
    ConType.FOREIGN_KEY: "foreign key",
    ConType.EXCLUSION: "exclusion",
}

# Constraint types that convergence can create and manage.
# Expand when support for new constraint types ships.
MANAGED_CONSTRAINT_TYPES: frozenset[ConType] = frozenset(
    {ConType.UNIQUE, ConType.CHECK, ConType.FOREIGN_KEY}
)


@dataclass
class ColumnState:
    """A column from pg_attribute."""

    type: str
    not_null: bool


@dataclass
class IndexState:
    """An index from pg_index + pg_am."""

    columns: list[str]
    access_method: str = DEFAULT_INDEX_ACCESS_METHOD
    is_unique: bool = False
    is_valid: bool = True
    definition: str | None = None


@dataclass
class ConstraintState:
    """A constraint from pg_constraint.

    All constraint types use this single class, matching Postgres's
    pg_constraint catalog. FK-specific fields (target_table, target_column)
    are only populated for foreign key constraints.
    """

    constraint_type: ConType
    columns: list[str]
    validated: bool = True
    definition: str | None = None
    target_table: str | None = None  # FK only
    target_column: str | None = None  # FK only


@dataclass
class TableState:
    """Raw database state for a single table.

    Mirrors Postgres's catalog structure:
    - columns from pg_attribute
    - indexes from pg_index + pg_am
    - constraints from pg_constraint (all types in one dict)
    """

    exists: bool = True
    columns: dict[str, ColumnState] = field(default_factory=dict)
    indexes: dict[str, IndexState] = field(default_factory=dict)
    constraints: dict[str, ConstraintState] = field(default_factory=dict)


def introspect_table(
    conn: DatabaseConnection, cursor: CursorWrapper, table_name: str
) -> TableState:
    """Query the database and return the raw state of a table."""
    actual_columns = _get_columns(cursor, table_name)
    if not actual_columns:
        return TableState(exists=False)

    raw = conn.get_constraints(cursor, table_name)

    indexes: dict[str, IndexState] = {}
    constraints: dict[str, ConstraintState] = {}

    for name, info in raw.items():
        raw_contype = info.get("contype")

        # Map raw contype to ConType enum if it's a known constraint type
        contype: ConType | None = None
        if raw_contype:
            try:
                contype = ConType(raw_contype)
            except ValueError:
                pass

        if contype in (
            ConType.PRIMARY,
            ConType.UNIQUE,
            ConType.CHECK,
            ConType.EXCLUSION,
        ):
            constraints[name] = ConstraintState(
                constraint_type=contype,
                columns=list(info.get("columns") or []),
                validated=info.get("validated", True),
                definition=info.get("definition"),
            )
        elif contype == ConType.FOREIGN_KEY:
            fk_target = info.get("foreign_key", ())
            fk_cols = info.get("columns", [])
            if len(fk_cols) == 1 and len(fk_target) == 2:
                constraints[name] = ConstraintState(
                    constraint_type=ConType.FOREIGN_KEY,
                    columns=fk_cols,
                    validated=info.get("validated", True),
                    definition=info.get("definition"),
                    target_table=fk_target[0],
                    target_column=fk_target[1],
                )
        elif info.get("index"):
            # get_constraints() encodes basic btree indexes as Index.suffix ("idx")
            # and non-btree indexes as their raw pg_am.amname. Reverse that here.
            raw_type = info.get("type", DEFAULT_INDEX_ACCESS_METHOD)
            access_method = (
                DEFAULT_INDEX_ACCESS_METHOD if raw_type == Index.suffix else raw_type
            )
            indexes[name] = IndexState(
                columns=list(info.get("columns") or []),
                access_method=access_method,
                is_unique=info.get("unique", False),
                is_valid=info.get("valid", True),
                definition=info.get("definition"),
            )

    return TableState(
        exists=True,
        columns=actual_columns,
        indexes=indexes,
        constraints=constraints,
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


def _strip_type_casts(s: str) -> str:
    """Strip PostgreSQL type casts (e.g. ''::text, 0::integer).

    PostgreSQL adds explicit casts to stored definitions (pg_get_indexdef,
    pg_get_constraintdef) but the ORM compiler omits them.  Only used for
    expression/condition comparison where the two generators diverge.
    """
    return re.sub(r"::\w+", "", s)


def normalize_check_definition(s: str) -> str:
    """Normalize a CHECK/condition definition for comparison.

    Strips the CHECK(...) wrapper, redundant parentheses, and PG type casts
    so that pg_get_constraintdef/pg_get_indexdef output and model-generated
    SQL can be compared.
    """
    s = _normalize_sql(s)
    s = _strip_type_casts(s)
    # Strip outer check(...)
    if s.startswith("check"):
        s = s[5:].strip()
        if s.startswith("(") and s.endswith(")"):
            s = s[1:-1].strip()
    s = _strip_balanced_parens(s)
    return s


def normalize_unique_definition(s: str) -> str:
    """Normalize a UNIQUE constraint definition for comparison.

    Strips the UNIQUE keyword so that pg_get_constraintdef output and
    model-generated definitions can be compared.  Handles INCLUDE and
    DEFERRABLE clauses that PostgreSQL emits.
    """
    s = _normalize_sql(s)
    if s.startswith("unique"):
        s = s[6:].strip()
    return s


def normalize_expression(s: str) -> str:
    """Normalize an index expression for comparison.

    Lowercases, strips quotes, collapses whitespace, and strips redundant
    outer parentheses.  Used for comparing the expression portion of index
    definitions (e.g. 'LOWER("col")' vs 'lower(col)').
    """
    return _strip_balanced_parens(_normalize_sql(s))


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

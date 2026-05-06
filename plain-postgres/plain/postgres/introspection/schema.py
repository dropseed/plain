from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from ..db import get_connection

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
    default_sql: str | None = None


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
    on_delete_action: str | None = None  # FK only: pg_constraint.confdeltype char


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
                    on_delete_action=info.get("on_delete_action"),
                )
        elif info.get("index"):
            indexes[name] = IndexState(
                columns=list(info.get("columns") or []),
                access_method=info.get("type", DEFAULT_INDEX_ACCESS_METHOD),
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


def _get_columns(cursor: CursorWrapper, table_name: str) -> dict[str, ColumnState]:
    """Return {column_name: ColumnState} from the actual DB."""
    cursor.execute(
        """
        SELECT a.attname,
               format_type(a.atttypid, a.atttypmod),
               a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid) AS column_default
        FROM pg_attribute a
        LEFT JOIN pg_attrdef d
               ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        JOIN pg_class c ON a.attrelid = c.oid
        WHERE c.relname = %s AND pg_catalog.pg_table_is_visible(c.oid)
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        [table_name],
    )
    return {
        name: ColumnState(type=type_str, not_null=is_not_null, default_sql=default_sql)
        for name, type_str, is_not_null, default_sql in cursor.fetchall()
    }

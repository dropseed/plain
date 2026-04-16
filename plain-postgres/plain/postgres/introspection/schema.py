from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import sqlparse
from sqlparse import tokens as T

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


def _strip_redundant_parens(s: str) -> str:
    """Strip balanced ``(...)`` groups that don't alter expression meaning.

    pg_get_expr rewrites stored defaults with aggressive grouping parens
    (e.g. ``(gen_random_uuid())``, ``(1 + mod(...))``) that the ORM compiler
    doesn't emit. For DEFAULT-expression drift comparison we normalize both
    sides by flattening every redundant paren pair outside string literals.

    Caveat: this does not preserve operator precedence — `(a + b) * c` and
    `a + b * c` would normalize identically. That's acceptable here because
    both sides come from the same expression source, so precedence is
    consistent.
    """
    if "(" not in s:
        return s
    out: list[str] = []
    n = len(s)
    i = 0
    in_single = False
    while i < n:
        ch = s[i]
        if in_single:
            out.append(ch)
            if ch == "'":
                # SQL doubles single quotes to escape them inside literals.
                if i + 1 < n and s[i + 1] == "'":
                    out.append(s[i + 1])
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if ch == "'":
            out.append(ch)
            in_single = True
            i += 1
            continue
        if ch == "(":
            # Find the matching `)` at the same depth.
            depth = 1
            j = i + 1
            j_in_single = False
            while j < n and depth:
                cj = s[j]
                if j_in_single:
                    if cj == "'":
                        if j + 1 < n and s[j + 1] == "'":
                            j += 2
                            continue
                        j_in_single = False
                elif cj == "'":
                    j_in_single = True
                elif cj == "(":
                    depth += 1
                elif cj == ")":
                    depth -= 1
                j += 1
            if depth != 0:
                # Unbalanced — leave the rest alone.
                out.append(s[i:])
                break
            inner = s[i + 1 : j - 1]
            stripped_inner = _strip_redundant_parens(inner)
            # A `(...)` is a function call's argument list when the char
            # immediately before it is an identifier char — those parens are
            # part of the call syntax and must stay.
            prev = out[-1] if out else ""
            is_function_args = bool(prev) and (prev.isalnum() or prev == "_")
            # Otherwise the parens are grouping: redundant iff the enclosed
            # expression contains no top-level comma (a comma would mean
            # we're inside a tuple/row-constructor, not a grouping).
            if is_function_args or _has_top_level_comma(stripped_inner):
                out.append("(" + stripped_inner + ")")
            else:
                out.append(stripped_inner)
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _has_top_level_comma(s: str) -> bool:
    depth = 0
    in_single = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if in_single:
            if ch == "'":
                if i + 1 < n and s[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if ch == "'":
            in_single = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            return True
        i += 1
    return False


def _normalize_sql(s: str) -> str:
    """Lowercase keywords/identifiers, strip quotes, collapse whitespace."""
    s = sqlparse.format(
        s, keyword_case="lower", identifier_case="lower", strip_whitespace=True
    )
    s = s.replace('"', "")
    return re.sub(r"\s+", " ", s).strip()


# Keyword-classified words that appear in PG's canonical multi-word type
# names (`character varying`, `time without time zone`, etc.). Kept narrow
# so operator keywords like `or`/`and` aren't mistaken for type continuations.
_TYPE_KEYWORD_WORDS = frozenset(
    {
        "bit",
        "character",
        "precision",
        "time",
        "timestamp",
        "varying",
        "with",
        "without",
        "zone",
    }
)


def _is_type_name(tok: Any) -> bool:
    # sqlparse's classification is inconsistent: builtin scalars (`text`/`int`)
    # come back Name.Builtin, unknown types (`varchar`/`numeric`) as Name, and
    # the reserved multi-word forms (`character varying`, `time without time
    # zone`) as Keyword/Keyword.CTE.
    if tok.ttype is T.Name or tok.ttype is T.Name.Builtin:
        return True
    if tok.ttype is T.Keyword or tok.ttype is T.Keyword.CTE:
        return tok.value.lower() in _TYPE_KEYWORD_WORDS
    return False


def _consume_type_name(tokens: list[Any], i: int) -> int:
    """Advance past a (possibly multi-word) type name starting at ``i``."""
    n = len(tokens)
    if i >= n or not _is_type_name(tokens[i]):
        return i
    j = i + 1
    while (
        j + 1 < n
        and tokens[j].ttype is T.Text.Whitespace
        and _is_type_name(tokens[j + 1])
    ):
        j += 2
    return j


def _consume_type_suffix(tokens: list[Any], i: int) -> int:
    """Skip over the tail of a type name: ``[]`` (array) or ``(N)`` / ``(N, M)``
    (parameterized type like varchar(10)). Returns the new token index.

    PG emits array type suffixes as bare ``[]`` in pg_get_expr output (sizes
    aren't enforced at the type level); fixed-size ``[N]`` or multi-dim
    ``[][]`` forms aren't handled here.
    """
    n = len(tokens)
    if i < n and tokens[i].ttype is T.Punctuation and tokens[i].value == "[":
        j = i + 1
        if j < n and tokens[j].ttype is T.Punctuation and tokens[j].value == "]":
            return j + 1
    if i < n and tokens[i].ttype is T.Punctuation and tokens[i].value == "(":
        depth = 1
        j = i + 1
        while j < n and depth:
            t = tokens[j]
            if t.ttype is T.Punctuation and t.value == "(":
                depth += 1
            elif t.ttype is T.Punctuation and t.value == ")":
                depth -= 1
            j += 1
        if depth == 0:
            return j
    return i


def _strip_type_casts(s: str) -> str:
    """Strip PostgreSQL type casts (e.g. ''::text, 0::integer, ::varchar(10),
    ::text[]) outside SQL single-quoted string literals.

    PostgreSQL adds explicit casts to stored definitions (pg_get_indexdef,
    pg_get_constraintdef, pg_get_expr) but the ORM compiler omits them.

    Also strips the grouping parens PG adds around a single identifier cast
    operand, e.g. (slug)::text → slug, so that lower((slug)::text) normalizes
    to lower(slug).
    """
    if "::" not in s:
        return s
    tokens = list(sqlparse.parse(s)[0].flatten())
    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        # (name)::type[(...)| []]?  →  name
        if (
            tok.ttype is T.Punctuation
            and tok.value == "("
            and i + 4 < n
            and tokens[i + 1].ttype in (T.Name, T.Name.Builtin)
            and tokens[i + 2].ttype is T.Punctuation
            and tokens[i + 2].value == ")"
            and tokens[i + 3].ttype is T.Punctuation
            and tokens[i + 3].value == "::"
            and _is_type_name(tokens[i + 4])
        ):
            out.append(tokens[i + 1].value)
            i = _consume_type_suffix(tokens, _consume_type_name(tokens, i + 4))
            continue
        # ::type[(...)| []]?
        if (
            tok.ttype is T.Punctuation
            and tok.value == "::"
            and i + 1 < n
            and _is_type_name(tokens[i + 1])
        ):
            i = _consume_type_suffix(tokens, _consume_type_name(tokens, i + 1))
            continue
        out.append(tok.value)
        i += 1
    return "".join(out)


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

    Lowercases, strips quotes, collapses whitespace, strips PG type casts,
    and strips redundant outer parentheses from each comma-separated term.

    Used for comparing the expression portion of index definitions
    (e.g. 'LOWER("col")' vs 'lower(col)').

    Type casts are stripped because pg_get_indexdef adds explicit casts
    (e.g. lower((slug)::text)) that the ORM compiler omits.  Per-term
    paren stripping is needed because the ORM wraps each IndexExpression
    in parentheses (e.g. '(LOWER("slug")), "team_id"') while PostgreSQL
    does not.
    """
    s = _normalize_sql(s)
    s = _strip_type_casts(s)
    # Split on top-level commas and normalize each term independently
    terms = _split_expression_terms(s)
    return ", ".join(_strip_balanced_parens(t.strip()) for t in terms)


def _split_expression_terms(s: str) -> list[str]:
    """Split an expression list on top-level commas, respecting parentheses."""
    terms = []
    depth = 0
    start = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            terms.append(s[start:i])
            start = i + 1
    terms.append(s[start:])
    return terms


def normalize_default_sql(s: str) -> str:
    """Normalize a column DEFAULT expression for comparison.

    pg_get_expr returns the stored DEFAULT with canonical lowercase function
    names (e.g. `gen_random_uuid()`, `statement_timestamp()`) and explicit
    type casts (e.g. `'pending'::text`).  The ORM compiler produces the same
    function names but without the casts, so we normalize both sides before
    comparing.
    """
    s = _normalize_sql(s)
    s = _strip_type_casts(s)
    s = _strip_redundant_parens(s)
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

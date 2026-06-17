from __future__ import annotations

import contextvars
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
from typing import TYPE_CHECKING, Any

import psycopg

from ..constraints import CheckConstraint, UniqueConstraint
from ..ddl import (
    build_include_sql,
    compile_database_default_sql,
    compile_expression_sql,
    compile_index_expressions_sql,
    compile_literal_default_sql,
    deferrable_sql,
)
from ..deletion import sql_on_delete
from ..dialect import quote_name
from ..fields.base import ColumnField
from ..fields.related import ForeignKeyField
from ..indexes import Index
from ..introspection import (
    MANAGED_CONSTRAINT_TYPES,
    MANAGED_INDEX_ACCESS_METHODS,
    ColumnState,
    ConstraintState,
    ConType,
    TableState,
    introspect_table,
)

if TYPE_CHECKING:
    from ..base import Model
    from ..connection import DatabaseConnection
    from ..expressions import Expression, ReplaceableExpression
    from ..fields import Field
    from ..query_utils import Q
    from ..utils import CursorWrapper


# Drift types — semantic descriptions of schema differences


class DriftKind(StrEnum):
    MISSING = "missing"
    INVALID = "invalid"
    CHANGED = "changed"
    RENAMED = "renamed"
    UNDECLARED = "undeclared"
    UNVALIDATED = "unvalidated"


@dataclass
class IndexDrift:
    """A schema difference for an index."""

    kind: DriftKind
    table: str
    index: Index | None = None
    model: type[Model] | None = None
    old_name: str | None = None
    new_name: str | None = None
    name: str | None = None

    def describe(self) -> str:
        match self.kind:
            case DriftKind.MISSING:
                assert self.index is not None
                return f"{self.table}: index {self.index.name} missing"
            case DriftKind.INVALID:
                assert self.index is not None
                return f"{self.table}: index {self.index.name} INVALID"
            case DriftKind.CHANGED:
                assert self.index is not None
                return f"{self.table}: index {self.index.name} definition changed"
            case DriftKind.RENAMED:
                return f"{self.table}: index {self.old_name} → {self.new_name}"
            case _:
                return f"{self.table}: index {self.name} not declared"


@dataclass
class ConstraintDrift:
    """A schema difference for a constraint."""

    kind: DriftKind
    table: str
    constraint: CheckConstraint | UniqueConstraint | None = None
    model: type[Model] | None = None
    old_name: str | None = None
    new_name: str | None = None
    name: str | None = None

    def describe(self) -> str:
        match self.kind:
            case DriftKind.MISSING:
                assert self.constraint is not None
                return f"{self.table}: constraint {self.constraint.name} missing"
            case DriftKind.UNVALIDATED:
                return f"{self.table}: constraint {self.name} NOT VALID"
            case DriftKind.CHANGED:
                assert self.constraint is not None
                return f"{self.table}: constraint {self.constraint.name} definition changed"
            case DriftKind.RENAMED:
                return f"{self.table}: constraint {self.old_name} → {self.new_name}"
            case _:
                return f"{self.table}: constraint {self.name} not declared"


@dataclass
class ForeignKeyDrift:
    """A schema difference for a foreign key constraint."""

    kind: DriftKind
    table: str
    name: str | None = None
    column: str | None = None
    target_table: str | None = None
    target_column: str | None = None
    on_delete_clause: str = ""  # SQL clause to emit, e.g. " ON DELETE CASCADE"
    actual_action: str | None = None  # CHANGED only: current DB confdeltype
    expected_action: str | None = None  # CHANGED only: expected confdeltype

    def describe(self) -> str:
        match self.kind:
            case DriftKind.MISSING:
                return f"{self.table}: FK {self.name} missing ({self.column} → {self.target_table}.{self.target_column})"
            case DriftKind.UNVALIDATED:
                return f"{self.table}: FK {self.name} NOT VALID"
            case DriftKind.CHANGED:
                return (
                    f"{self.table}: FK {self.name} on_delete changed "
                    f"({self.actual_action!r} → {self.expected_action!r})"
                )
            case _:
                return f"{self.table}: FK {self.name} not declared"


@dataclass
class NullabilityDrift:
    """Mismatch between model and DB column nullability."""

    table: str
    column: str
    model_allows_null: bool
    has_null_rows: bool = False  # Only checked when model_allows_null is False

    def describe(self) -> str:
        if not self.model_allows_null:
            if self.has_null_rows:
                return (
                    f"{self.table}: column {self.column} allows NULL (NULL rows exist)"
                )
            return f"{self.table}: column {self.column} allows NULL"
        return f"{self.table}: column {self.column} is NOT NULL, model allows NULL"


@dataclass
class ColumnDefaultDrift:
    """Mismatch between the model's declared default and the DB column DEFAULT."""

    kind: DriftKind
    table: str
    column: str
    db_default_sql: str | None
    model_default_sql: str | None

    def describe(self) -> str:
        match self.kind:
            case DriftKind.MISSING:
                return (
                    f"{self.table}: column {self.column} missing DEFAULT "
                    f"(expected {self.model_default_sql})"
                )
            case DriftKind.CHANGED:
                return (
                    f"{self.table}: column {self.column} DEFAULT mismatch — "
                    f"db has {self.db_default_sql}, model declares "
                    f"{self.model_default_sql}"
                )
            case _:
                return (
                    f"{self.table}: column {self.column} has undeclared DEFAULT "
                    f"{self.db_default_sql}"
                )


@dataclass
class StorageParameterDrift:
    """Mismatch between declared and live `pg_class.reloptions` for a table.

    `key` carries a `toast.` prefix when the parameter belongs to the table's
    TOAST relation; convergence emits and reads it accordingly.
    """

    kind: DriftKind
    table: str
    key: str
    declared_value: str | None = None
    actual_value: str | None = None

    def describe(self) -> str:
        match self.kind:
            case DriftKind.MISSING:
                return (
                    f"{self.table}: storage parameter {self.key} missing "
                    f"(expected {self.declared_value})"
                )
            case DriftKind.CHANGED:
                return (
                    f"{self.table}: storage parameter {self.key} mismatch — "
                    f"db has {self.actual_value}, model declares "
                    f"{self.declared_value}"
                )
            case _:
                return (
                    f"{self.table}: storage parameter {self.key} not declared "
                    f"(db has {self.actual_value})"
                )


type ColumnDrift = NullabilityDrift | ColumnDefaultDrift
type Drift = (
    IndexDrift | ConstraintDrift | ForeignKeyDrift | ColumnDrift | StorageParameterDrift
)


# Status objects — analysis results with optional drift


@dataclass
class ColumnStatus:
    name: str
    field_name: str
    type: str
    nullable: bool
    primary_key: bool
    pk_suffix: str
    issue: str | None = None
    drifts: list[ColumnDrift] = field(default_factory=list)


@dataclass
class IndexStatus:
    name: str
    fields: list[str] = field(default_factory=list)
    issue: str | None = None
    drift: IndexDrift | None = None
    access_method: str | None = None  # set for unmanaged indexes (display only)


@dataclass
class ConstraintStatus:
    name: str
    constraint_type: ConType
    fields: list[str] = field(default_factory=list)
    issue: str | None = None
    drift: ConstraintDrift | ForeignKeyDrift | IndexDrift | None = None


@dataclass
class ModelAnalysis:
    label: str
    table: str
    table_issues: list[str] = field(default_factory=list)
    columns: list[ColumnStatus] = field(default_factory=list)
    indexes: list[IndexStatus] = field(default_factory=list)
    constraints: list[ConstraintStatus] = field(default_factory=list)
    storage_parameter_drifts: list[StorageParameterDrift] = field(default_factory=list)

    @cached_property
    def drifts(self) -> list[Drift]:
        """All detected schema drifts."""
        result: list[Drift] = []
        for col in self.columns:
            result.extend(col.drifts)
        for idx in self.indexes:
            if idx.drift:
                result.append(idx.drift)
        for con in self.constraints:
            if con.drift:
                result.append(con.drift)
        result.extend(self.storage_parameter_drifts)
        return result

    @cached_property
    def issue_count(self) -> int:
        """Total issues (table + columns + indexes + constraints + storage)."""
        count = len(self.table_issues)
        count += sum(1 for col in self.columns if col.issue)
        count += sum(1 for idx in self.indexes if idx.issue)
        count += sum(1 for con in self.constraints if con.issue)
        count += len(self.storage_parameter_drifts)
        return count

    def to_dict(self) -> dict[str, Any]:
        """Serialize for --json output."""
        return {
            "label": self.label,
            "table": self.table,
            "table_issues": self.table_issues,
            "columns": [
                {
                    "name": col.name,
                    "field_name": col.field_name,
                    "type": col.type,
                    "nullable": col.nullable,
                    "primary_key": col.primary_key,
                    "pk_suffix": col.pk_suffix,
                    "issue": col.issue,
                    "drifts": [d.describe() for d in col.drifts],
                }
                for col in self.columns
            ],
            "indexes": [
                {
                    "name": idx.name,
                    "fields": idx.fields,
                    "access_method": idx.access_method,
                    "issue": idx.issue,
                    "drift": idx.drift.describe() if idx.drift else None,
                }
                for idx in self.indexes
            ],
            "constraints": [
                {
                    "name": con.name,
                    "constraint_type": con.constraint_type,
                    "type_label": con.constraint_type.label,
                    "fields": con.fields,
                    "issue": con.issue,
                    "drift": con.drift.describe() if con.drift else None,
                }
                for con in self.constraints
            ],
            "storage_parameter_drifts": [
                {
                    "key": d.key,
                    "kind": d.kind,
                    "declared_value": d.declared_value,
                    "actual_value": d.actual_value,
                }
                for d in self.storage_parameter_drifts
            ],
        }


def analyze_model(
    conn: DatabaseConnection, cursor: CursorWrapper, model: type[Model]
) -> ModelAnalysis:
    """Compare a model against the database and classify each difference.

    Introspects the actual table state, compares it against model definitions,
    and produces a ModelAnalysis where each column/index/constraint carries its
    issue (if any) and drift object (if schema differs).
    """
    table_name = model.model_options.db_table
    db = introspect_table(conn, cursor, table_name)

    if not db.exists:
        return ModelAnalysis(
            label=model.model_options.label,
            table=table_name,
            table_issues=["table missing from database"],
        )

    with _probe_session(cursor, model):
        return ModelAnalysis(
            label=model.model_options.label,
            table=table_name,
            columns=_compare_columns(model, db, table_name, cursor),
            indexes=_compare_indexes(cursor, model, db, table_name),
            constraints=_compare_constraints(cursor, model, db, table_name),
            storage_parameter_drifts=_compare_storage_parameters(model, db, table_name),
        )


def _compare_storage_parameters(
    model: type[Model], db: TableState, table: str
) -> list[StorageParameterDrift]:
    """Diff declared `model_options.storage_parameters` against `pg_class.reloptions`.

    Declared keys missing from the DB → MISSING. Mismatched values → CHANGED.
    Live keys not declared → UNDECLARED (so convergence can RESET them, keeping
    the model as the source of truth — matches how indexes/constraints work).
    """
    declared = model.model_options.storage_parameters
    actual = db.storage_parameters
    drifts: list[StorageParameterDrift] = []

    for key, declared_value in declared.items():
        actual_value = actual.get(key)
        if actual_value is None:
            drifts.append(
                StorageParameterDrift(
                    kind=DriftKind.MISSING,
                    table=table,
                    key=key,
                    declared_value=declared_value,
                )
            )
        elif actual_value != declared_value:
            drifts.append(
                StorageParameterDrift(
                    kind=DriftKind.CHANGED,
                    table=table,
                    key=key,
                    declared_value=declared_value,
                    actual_value=actual_value,
                )
            )

    for key, actual_value in actual.items():
        if key not in declared:
            drifts.append(
                StorageParameterDrift(
                    kind=DriftKind.UNDECLARED,
                    table=table,
                    key=key,
                    actual_value=actual_value,
                )
            )

    return drifts


# Column comparison


def _column_has_nulls(cursor: CursorWrapper, table: str, column: str) -> bool:
    """Check whether any NULL values exist in a column."""
    cursor.execute(
        f"SELECT 1 FROM {quote_name(table)} WHERE {quote_name(column)} IS NULL LIMIT 1"
    )
    return cursor.fetchone() is not None


def _compare_columns(
    model: type[Model], db: TableState, table: str, cursor: CursorWrapper
) -> list[ColumnStatus]:
    statuses: list[ColumnStatus] = []
    expected_col_names: set[str] = set()

    for f in model._model_meta.local_fields:
        if not isinstance(f, ColumnField):
            continue
        db_type = f.db_type()
        if db_type is None:
            continue

        expected_col_names.add(f.column)
        issue: str | None = None
        drifts: list[ColumnDrift] = []

        if f.column not in db.columns:
            issue = "missing from database"
        else:
            actual = db.columns[f.column]
            if db_type != actual.type:
                issue = f"expected {db_type}, actual {actual.type}"
            elif not f.allow_null and not actual.not_null:
                # Model says NOT NULL, DB allows NULL — semantic drift
                has_nulls = _column_has_nulls(cursor, table, f.column)
                if has_nulls:
                    issue = "expected NOT NULL, actual NULL (NULL rows exist)"
                else:
                    issue = "expected NOT NULL, actual NULL"
                drifts.append(
                    NullabilityDrift(
                        table=table,
                        column=f.column,
                        model_allows_null=False,
                        has_null_rows=has_nulls,
                    )
                )
            elif f.allow_null and actual.not_null:
                issue = "expected NULL, actual NOT NULL"
                drifts.append(
                    NullabilityDrift(
                        table=table,
                        column=f.column,
                        model_allows_null=True,
                    )
                )

            if default_drift := _compare_column_default(cursor, f, actual, table):
                drifts.append(default_drift)
                if issue is None:
                    issue = default_drift.describe()

        pk_suffix = ""
        if f.primary_key:
            pk_suffix = f.db_type_suffix() or ""

        assert f.name is not None
        statuses.append(
            ColumnStatus(
                name=f.column,
                field_name=f.name,
                type=db_type,
                nullable=f.allow_null,
                primary_key=f.primary_key,
                pk_suffix=pk_suffix,
                issue=issue,
                drifts=drifts,
            )
        )

    for col_name in sorted(db.columns.keys() - expected_col_names):
        actual = db.columns[col_name]
        statuses.append(
            ColumnStatus(
                name=col_name,
                field_name="",
                type=actual.type,
                nullable=not actual.not_null,
                primary_key=False,
                pk_suffix="",
                issue="extra column, not in model",
            )
        )

    return statuses


_JSONB_LITERAL_RE = re.compile(r"^\s*'((?:[^']|'')*)'::jsonb\s*$", re.IGNORECASE)


def _extract_jsonb_literal(sql: str) -> str | None:
    m = _JSONB_LITERAL_RE.match(sql)
    if m is None:
        return None
    return m.group(1).replace("''", "'")


def _normalize_default_expr(
    cursor: CursorWrapper, model: type[Model], column: str, default_sql: str
) -> str:
    """Round-trip a column DEFAULT through Postgres so both sides of the
    comparison go through pg_get_expr — the live default comes from
    `pg_attrdef.adbin` during introspection, and the expected side is set on
    the temp table column then read the same way.

    Returns "" if the model SQL is incompatible with the live column shape;
    comparison then sees inequality and reports drift.
    """
    try:
        with _probe_table(cursor, model):
            cursor.execute(
                f"ALTER TABLE {_PROBE_TABLE} ALTER COLUMN {quote_name(column)} "
                f"SET DEFAULT {default_sql}"
            )
            cursor.execute(
                "SELECT pg_get_expr(ad.adbin, ad.adrelid) FROM pg_attrdef ad "
                "JOIN pg_attribute a ON a.attnum = ad.adnum AND a.attrelid = ad.adrelid "
                "WHERE a.attrelid = (SELECT oid FROM pg_class WHERE relname = %s "
                "AND relnamespace = pg_my_temp_schema()) "
                "AND a.attname = %s",
                [_PROBE_TABLE, column],
            )
            row = cursor.fetchone()
            return row[0] if row else ""
    except _PROBE_FALLBACK_ERRORS:
        return ""


def _compare_column_default(
    cursor: CursorWrapper, field: Field, actual: ColumnState, table: str
) -> ColumnDefaultDrift | None:
    expected_sql: str | None = None
    db_default_expr = field.get_db_default_expression()
    if db_default_expr is not None:
        expected_sql = compile_database_default_sql(db_default_expr)
    elif field.has_persistent_literal_default():
        expected_sql = compile_literal_default_sql(field)

    if expected_sql is not None:
        if actual.default_sql is None:
            return ColumnDefaultDrift(
                kind=DriftKind.MISSING,
                table=table,
                column=field.column,
                db_default_sql=None,
                model_default_sql=expected_sql,
            )

        normalized_expected = _normalize_default_expr(
            cursor, field.model, field.column, expected_sql
        )
        if normalized_expected == actual.default_sql:
            return None
        # Semantic compare for jsonb — PG normalizes object keys, which
        # won't match Python's dict-insertion order even after a round-trip.
        m_json = _extract_jsonb_literal(normalized_expected)
        d_json = _extract_jsonb_literal(actual.default_sql)
        if m_json is not None and d_json is not None:
            try:
                if json.loads(m_json) == json.loads(d_json):
                    return None
            except json.JSONDecodeError:
                pass

        return ColumnDefaultDrift(
            kind=DriftKind.CHANGED,
            table=table,
            column=field.column,
            db_default_sql=actual.default_sql,
            model_default_sql=expected_sql,
        )

    if actual.default_sql is None:
        return None

    return ColumnDefaultDrift(
        kind=DriftKind.UNDECLARED,
        table=table,
        column=field.column,
        db_default_sql=actual.default_sql,
        model_default_sql=None,
    )


# Index comparison with rename detection


def _compare_indexes(
    cursor: CursorWrapper, model: type[Model], db: TableState, table: str
) -> list[IndexStatus]:
    statuses: list[IndexStatus] = []
    missing: list[Index] = []
    model_index_names = {idx.name for idx in model.model_options.indexes}
    # Unique indexes are handled by _compare_unique_constraints, not here.
    # Also exclude indexes that back unique constraints in pg_constraint.
    unique_constraint_names = {
        k for k, v in db.constraints.items() if v.constraint_type == ConType.UNIQUE
    }
    non_unique_indexes = {
        k: v
        for k, v in db.indexes.items()
        if not v.is_unique and k not in unique_constraint_names
    }

    for index in model.model_options.indexes:
        if index.name not in non_unique_indexes:
            missing.append(index)
            continue

        db_idx = non_unique_indexes[index.name]

        # Name collision: DB has an unmanaged index type with this name
        if db_idx.access_method not in MANAGED_INDEX_ACCESS_METHODS:
            statuses.append(
                IndexStatus(
                    name=index.name,
                    fields=list(index.fields),
                    issue=f"name conflict with {db_idx.access_method} index — rename one to resolve",
                )
            )
            continue

        if not db_idx.is_valid:
            statuses.append(
                IndexStatus(
                    name=index.name,
                    fields=list(index.fields),
                    issue="INVALID — needs drop and recreate",
                    drift=IndexDrift(
                        kind=DriftKind.INVALID,
                        table=table,
                        index=index,
                        model=model,
                    ),
                )
            )
            continue

        # Check if definition matches
        if db_idx.definition:
            issue = _compare_normalized_index(
                cursor=cursor,
                model=model,
                expressions=index.expressions,
                fields_orders=list(index.fields_orders),
                opclasses=list(index.opclasses),
                condition=index.condition,
                include=index.include,
                actual_def=db_idx.definition,
            )
            if issue:
                statuses.append(
                    IndexStatus(
                        name=index.name,
                        fields=list(index.fields),
                        issue=issue,
                        drift=IndexDrift(
                            kind=DriftKind.CHANGED,
                            table=table,
                            index=index,
                            model=model,
                        ),
                    )
                )
                continue

        # Index exists and matches
        statuses.append(
            IndexStatus(
                name=index.name,
                fields=list(index.fields),
            )
        )

    # Extra indexes (in DB but not in model)
    extra_names = sorted(non_unique_indexes.keys() - model_index_names)

    # Only managed index types participate in rename detection
    managed_extra = [
        n
        for n in extra_names
        if non_unique_indexes[n].access_method in MANAGED_INDEX_ACCESS_METHODS
    ]

    # Detect renames by normalized (round-tripped) index body. Build the cheap
    # already-introspected side first so we can skip the per-missing
    # normalization loop on the steady-state path.
    renamed_missing: set[str] = set()
    renamed_extra: set[str] = set()

    extra_by_def: dict[str, list[str]] = {}
    for name in managed_extra:
        defn = non_unique_indexes[name].definition
        if defn:
            extra_by_def.setdefault(_index_def_tail(defn), []).append(name)

    missing_by_def: dict[str, list[Index]] = {}
    if extra_by_def:
        for index in missing:
            expected_tail = _normalize_index_def(
                cursor,
                model,
                expressions=index.expressions,
                fields_orders=list(index.fields_orders),
                opclasses=list(index.opclasses),
                condition=index.condition,
                include=index.include,
            )
            if not expected_tail:
                # Normalization failed; bucketing under "" would conflate
                # multiple sentinel-failing indexes and disable rename
                # detection for the rest.
                continue
            missing_by_def.setdefault(expected_tail, []).append(index)

    for tail, m_list in missing_by_def.items():
        e_list = extra_by_def.get(tail)
        if e_list and len(m_list) == 1 and len(e_list) == 1:
            index = m_list[0]
            old_name = e_list[0]
            statuses.append(
                IndexStatus(
                    name=index.name,
                    fields=list(index.fields),
                    issue=f"rename from {old_name}",
                    drift=IndexDrift(
                        kind=DriftKind.RENAMED,
                        table=table,
                        old_name=old_name,
                        new_name=index.name,
                    ),
                )
            )
            renamed_missing.add(index.name)
            renamed_extra.add(old_name)

    # Remaining unmatched missing
    for index in missing:
        if index.name not in renamed_missing:
            statuses.append(
                IndexStatus(
                    name=index.name,
                    fields=list(index.fields),
                    issue="missing from database",
                    drift=IndexDrift(
                        kind=DriftKind.MISSING,
                        table=table,
                        index=index,
                        model=model,
                    ),
                )
            )

    # Extra managed indexes are undeclared
    for name in managed_extra:
        if name not in renamed_extra:
            statuses.append(
                IndexStatus(
                    name=name,
                    fields=non_unique_indexes[name].columns,
                    issue="not in model",
                    drift=IndexDrift(
                        kind=DriftKind.UNDECLARED,
                        table=table,
                        name=name,
                    ),
                )
            )

    # Extra unmanaged indexes — informational only, no drift
    for name in extra_names:
        idx = non_unique_indexes[name]
        if idx.access_method not in MANAGED_INDEX_ACCESS_METHODS:
            statuses.append(
                IndexStatus(
                    name=name,
                    fields=idx.columns,
                    access_method=idx.access_method,
                )
            )

    return statuses


# Constraint comparison


def _compare_constraints(
    cursor: CursorWrapper, model: type[Model], db: TableState, table: str
) -> list[ConstraintStatus]:
    statuses: list[ConstraintStatus] = []
    statuses.extend(_compare_unique_constraints(cursor, model, db, table))
    statuses.extend(_compare_check_constraints(cursor, model, db, table))
    statuses.extend(_compare_foreign_keys(model, db, table))

    # Unmanaged constraint types — informational only, no drift.
    # Primary keys are also unmanaged but not shown.
    for name, cs in db.constraints.items():
        if (
            cs.constraint_type not in MANAGED_CONSTRAINT_TYPES
            and cs.constraint_type != ConType.PRIMARY
        ):
            statuses.append(
                ConstraintStatus(
                    name=name,
                    constraint_type=cs.constraint_type,
                    fields=cs.columns,
                )
            )

    return statuses


def _compare_unique_constraints(
    cursor: CursorWrapper, model: type[Model], db: TableState, table: str
) -> list[ConstraintStatus]:
    statuses: list[ConstraintStatus] = []
    # Unique constraints from pg_constraint (contype='u')
    actual_constraints = {
        k: v for k, v in db.constraints.items() if v.constraint_type == ConType.UNIQUE
    }
    # Unique indexes from pg_index that don't have a backing pg_constraint
    # (e.g. partial/expression unique indexes created with CREATE UNIQUE INDEX)
    actual_indexes = {
        k: ConstraintState(
            constraint_type=ConType.UNIQUE,
            columns=v.columns,
            validated=True,
            definition=v.definition,
        )
        for k, v in db.indexes.items()
        if v.is_unique and k not in actual_constraints
    }
    actual = {**actual_constraints, **actual_indexes}
    model_constraints = [
        c for c in model.model_options.constraints if isinstance(c, UniqueConstraint)
    ]
    expected_names = {c.name for c in model_constraints}
    extra_names = sorted(actual.keys() - expected_names)

    missing: list[UniqueConstraint] = []
    for constraint in model_constraints:
        if constraint.name not in actual:
            missing.append(constraint)
            continue

        issue: str | None = None
        drift: ConstraintDrift | None = None

        if not actual[constraint.name].validated:
            issue = "NOT VALID — needs validation"
            drift = ConstraintDrift(
                kind=DriftKind.UNVALIDATED,
                table=table,
                name=constraint.name,
            )
        elif constraint.index_only:
            issue, drift = _compare_index_only_unique(
                cursor, model, constraint, actual[constraint.name], table
            )
        elif actual_def := actual[constraint.name].definition:
            expected_def = _get_expected_unique_definition(cursor, model, constraint)
            # Both sides are deparsed by pg_get_constraintdef → string equality.
            if actual_def != expected_def:
                if expected_def:
                    issue = f"definition differs: DB has {actual_def!r}, model expects {expected_def!r}"
                else:
                    # Round-trip normalization couldn't complete; normalized
                    # model text is unavailable for the diagnostic.
                    issue = f"definition differs: DB has {actual_def!r}"
                drift = ConstraintDrift(
                    kind=DriftKind.CHANGED,
                    table=table,
                    constraint=constraint,
                    model=model,
                )

        statuses.append(
            ConstraintStatus(
                name=constraint.name,
                constraint_type=ConType.UNIQUE,
                fields=list(constraint.fields),
                issue=issue,
                drift=drift,
            )
        )

    # Detect renames by columns
    rename_statuses, renamed_missing, renamed_extra = _detect_unique_renames(
        cursor, missing, extra_names, actual, model, table
    )
    statuses.extend(rename_statuses)

    for constraint in missing:
        if constraint.name not in renamed_missing:
            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    constraint_type=ConType.UNIQUE,
                    fields=list(constraint.fields),
                    issue="missing from database",
                    drift=ConstraintDrift(
                        kind=DriftKind.MISSING,
                        table=table,
                        constraint=constraint,
                        model=model,
                    ),
                )
            )

    for name in extra_names:
        if name not in renamed_extra:
            # Index-only entries (from pg_index, not pg_constraint) need
            # IndexDrift so the planner uses DROP INDEX, not DROP CONSTRAINT.
            undeclared_drift: Drift
            if name in actual_indexes:
                undeclared_drift = IndexDrift(
                    kind=DriftKind.UNDECLARED, table=table, name=name
                )
            else:
                undeclared_drift = ConstraintDrift(
                    kind=DriftKind.UNDECLARED, table=table, name=name
                )
            statuses.append(
                ConstraintStatus(
                    name=name,
                    constraint_type=ConType.UNIQUE,
                    fields=actual[name].columns,
                    issue="not in model",
                    drift=undeclared_drift,
                )
            )

    return statuses


def _compare_check_constraints(
    cursor: CursorWrapper, model: type[Model], db: TableState, table: str
) -> list[ConstraintStatus]:
    statuses: list[ConstraintStatus] = []
    actual = {
        k: v for k, v in db.constraints.items() if v.constraint_type == ConType.CHECK
    }
    model_constraints = [
        c for c in model.model_options.constraints if isinstance(c, CheckConstraint)
    ]
    expected_names = {c.name for c in model_constraints}
    extra_names = sorted(actual.keys() - expected_names)

    missing: list[CheckConstraint] = []
    for constraint in model_constraints:
        if constraint.name not in actual:
            missing.append(constraint)
            continue

        issue: str | None = None
        drift: ConstraintDrift | None = None

        if not actual[constraint.name].validated:
            issue = "NOT VALID — needs validation"
            drift = ConstraintDrift(
                kind=DriftKind.UNVALIDATED,
                table=table,
                name=constraint.name,
            )
        elif actual_def := actual[constraint.name].definition:
            expected_def = _get_expected_check_definition(cursor, model, constraint)
            # Both sides are deparsed by pg_get_constraintdef → string equality.
            if actual_def != expected_def:
                if expected_def:
                    issue = f"definition differs: DB has {actual_def!r}, model expects {expected_def!r}"
                else:
                    # Round-trip normalization couldn't complete; normalized
                    # model text is unavailable for the diagnostic.
                    issue = f"definition differs: DB has {actual_def!r}"
                drift = ConstraintDrift(
                    kind=DriftKind.CHANGED,
                    table=table,
                    constraint=constraint,
                    model=model,
                )

        statuses.append(
            ConstraintStatus(
                name=constraint.name,
                constraint_type=ConType.CHECK,
                fields=[],
                issue=issue,
                drift=drift,
            )
        )

    # Detect renames by definition
    rename_statuses, renamed_missing, renamed_extra = _detect_check_renames(
        cursor, missing, extra_names, actual, model, table
    )
    statuses.extend(rename_statuses)

    for constraint in missing:
        if constraint.name not in renamed_missing:
            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    constraint_type=ConType.CHECK,
                    fields=[],
                    issue="missing from database",
                    drift=ConstraintDrift(
                        kind=DriftKind.MISSING,
                        table=table,
                        constraint=constraint,
                        model=model,
                    ),
                )
            )

    # Build set of framework-owned temp NOT NULL check names so leftover
    # artifacts from a partially-completed SetNotNullFix are silently
    # ignored rather than surfaced as undeclared user constraints.
    internal_checks = {
        generate_notnull_check_name(table, f.column)
        for f in model._model_meta.local_fields
        if f.db_type() is not None
    }

    for name in extra_names:
        if name not in renamed_extra and name not in internal_checks:
            statuses.append(
                ConstraintStatus(
                    name=name,
                    constraint_type=ConType.CHECK,
                    fields=actual[name].columns,
                    issue="not in model",
                    drift=ConstraintDrift(
                        kind=DriftKind.UNDECLARED,
                        table=table,
                        name=name,
                    ),
                )
            )

    return statuses


def _compare_foreign_keys(
    model: type[Model], db: TableState, table: str
) -> list[ConstraintStatus]:
    statuses: list[ConstraintStatus] = []
    actual = {
        k: v
        for k, v in db.constraints.items()
        if v.constraint_type == ConType.FOREIGN_KEY
    }

    # Build expected FKs from model fields.
    # Key: shape (column, target_table, target_column)
    # Value: (field_name, constraint_name, expected_on_delete_clause, expected_confdeltype)
    expected_fks: dict[tuple[str, str, str], tuple[str, str, str, str]] = {}
    for f in model._model_meta.local_fields:
        if isinstance(f, ForeignKeyField) and f.db_constraint:
            assert f.name is not None
            to_table = f.target_field.model.model_options.db_table
            to_column = f.target_field.column
            constraint_name = generate_fk_constraint_name(
                table, f.column, to_table, to_column
            )
            on_delete_clause, confdeltype = sql_on_delete(f.remote_field.on_delete)
            expected_fks[(f.column, to_table, to_column)] = (
                f.name,
                constraint_name,
                on_delete_clause,
                confdeltype,
            )

    # Build actual FKs from DB: shape → (constraint_name, ConstraintState)
    actual_fk_by_shape: dict[tuple[str, str, str], tuple[str, ConstraintState]] = {}
    for name, cs in actual.items():
        if cs.target_table and cs.target_column and cs.columns:
            actual_fk_by_shape[(cs.columns[0], cs.target_table, cs.target_column)] = (
                name,
                cs,
            )

    matched_fk_names: set[str] = set()
    for key, (
        field_name,
        constraint_name,
        on_delete_clause,
        expected_action,
    ) in expected_fks.items():
        if match := actual_fk_by_shape.get(key):
            actual_name, cs = match
            matched_fk_names.add(actual_name)

            issue: str | None = None
            drift: ForeignKeyDrift | None = None

            # on_delete action mismatch — drop + re-add with new clause
            if (
                cs.on_delete_action is not None
                and cs.on_delete_action != expected_action
            ):
                issue = (
                    f"on_delete action differs "
                    f"({cs.on_delete_action!r} → {expected_action!r})"
                )
                col, to_table, to_column = key
                drift = ForeignKeyDrift(
                    kind=DriftKind.CHANGED,
                    table=table,
                    name=actual_name,
                    column=col,
                    target_table=to_table,
                    target_column=to_column,
                    on_delete_clause=on_delete_clause,
                    actual_action=cs.on_delete_action,
                    expected_action=expected_action,
                )
            elif not cs.validated:
                issue = "NOT VALID — needs validation"
                drift = ForeignKeyDrift(
                    kind=DriftKind.UNVALIDATED,
                    table=table,
                    name=actual_name,
                )

            statuses.append(
                ConstraintStatus(
                    name=actual_name,
                    constraint_type=ConType.FOREIGN_KEY,
                    fields=[key[0]],
                    issue=issue,
                    drift=drift,
                )
            )
        else:
            col, to_table, to_column = key
            statuses.append(
                ConstraintStatus(
                    name=f"{field_name} → {to_table}.{to_column}",
                    constraint_type=ConType.FOREIGN_KEY,
                    fields=[col],
                    issue="missing from database",
                    drift=ForeignKeyDrift(
                        kind=DriftKind.MISSING,
                        table=table,
                        name=constraint_name,
                        column=col,
                        target_table=to_table,
                        target_column=to_column,
                        on_delete_clause=on_delete_clause,
                    ),
                )
            )

    for name in sorted(actual.keys() - matched_fk_names):
        cs = actual[name]
        statuses.append(
            ConstraintStatus(
                name=name,
                constraint_type=ConType.FOREIGN_KEY,
                fields=cs.columns,
                issue=f"not in model (→ {cs.target_table}.{cs.target_column})",
                drift=ForeignKeyDrift(
                    kind=DriftKind.UNDECLARED,
                    table=table,
                    name=name,
                ),
            )
        )

    return statuses


def generate_notnull_check_name(table: str, column: str) -> str:
    """Generate a hashed name for the temporary NOT NULL check constraint.

    Used by SetNotNullFix for the CHECK NOT VALID → VALIDATE → SET NOT NULL
    pattern, and by analysis to recognize (and ignore) leftover temp checks.
    """
    from ..utils import generate_identifier_name

    return generate_identifier_name(table, [column], "_notnull")


def generate_fk_constraint_name(
    table: str, column: str, target_table: str, target_column: str
) -> str:
    """Generate a deterministic FK constraint name.

    Uses the same naming algorithm as the schema editor so that
    convergence-created FKs match migration-created ones.
    """
    from ..utils import generate_identifier_name, split_identifier

    _, target_table_name = split_identifier(target_table)
    suffix = f"_fk_{target_table_name}_{target_column}"
    return generate_identifier_name(table, [column], suffix)


def _detect_unique_renames(
    cursor: CursorWrapper,
    missing: list[UniqueConstraint],
    extra_names: list[str],
    actual_dict: dict[str, ConstraintState],
    model: type[Model],
    table: str,
) -> tuple[list[ConstraintStatus], set[str], set[str]]:
    """Match missing and extra unique constraints by structure.

    Constraint-backed (not index_only): matched by resolved column tuple.
    Index-only (condition/expression/opclass): matched by normalized
    (round-tripped) index definition, which captures the full semantics
    including WHERE clauses, opclasses, and expressions.
    """
    statuses: list[ConstraintStatus] = []
    renamed_missing: set[str] = set()
    renamed_extra: set[str] = set()

    # Phase 1: Field-based — match by resolved column tuple.
    # Covers both constraint-backed and index-only field-based constraints.
    missing_by_cols: dict[tuple[str, ...], list[UniqueConstraint]] = {}
    for constraint in missing:
        if not constraint.fields:
            continue
        cols = tuple(
            model._model_meta.get_forward_field(field_name).column
            for field_name in constraint.fields
        )
        missing_by_cols.setdefault(cols, []).append(constraint)

    extra_by_cols: dict[tuple[str, ...], list[str]] = {}
    for name in extra_names:
        cols = tuple(actual_dict[name].columns)
        if cols:
            extra_by_cols.setdefault(cols, []).append(name)

    for cols, m_list in missing_by_cols.items():
        e_list = extra_by_cols.get(cols)
        if e_list and len(m_list) == 1 and len(e_list) == 1:
            constraint = m_list[0]
            old_name = e_list[0]
            # For index-only uniques, same columns isn't enough — the
            # condition or opclass may have changed.  Verify the full
            # definition matches before accepting a rename, otherwise
            # let both sides fall through as separate missing + undeclared.
            if constraint.index_only:
                old_def = actual_dict[old_name].definition
                if not old_def:
                    continue
                expected_tail = _normalize_index_def(
                    cursor,
                    model,
                    expressions=constraint.expressions,
                    fields_orders=[(f, "") for f in constraint.fields],
                    opclasses=list(constraint.opclasses)
                    if constraint.opclasses
                    else [],
                    condition=constraint.condition,
                    include=constraint.include,
                    unique=True,
                )
                if _index_def_tail(old_def) != expected_tail:
                    continue
            DriftType = IndexDrift if constraint.index_only else ConstraintDrift
            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    constraint_type=ConType.UNIQUE,
                    fields=list(constraint.fields),
                    issue=f"rename from {old_name}",
                    drift=DriftType(
                        kind=DriftKind.RENAMED,
                        table=table,
                        old_name=old_name,
                        new_name=constraint.name,
                    ),
                )
            )
            renamed_missing.add(constraint.name)
            renamed_extra.add(old_name)

    # Phase 2: Expression-based — match by normalized (round-tripped) index
    # body. Build the cheap already-introspected extras side first so we can
    # skip the per-missing round-trip on the steady-state path.
    extra_by_def: dict[str, list[str]] = {}
    for name in extra_names:
        if name in renamed_extra:
            continue
        defn = actual_dict[name].definition
        if defn:
            extra_by_def.setdefault(_index_def_tail(defn), []).append(name)

    missing_by_def: dict[str, list[UniqueConstraint]] = {}
    if extra_by_def:
        for constraint in missing:
            if constraint.fields or constraint.name in renamed_missing:
                continue
            # constraint.fields is empty here (filtered above), so this is
            # the expression-based path — fields_orders is unused.
            expected_tail = _normalize_index_def(
                cursor,
                model,
                expressions=constraint.expressions,
                opclasses=list(constraint.opclasses),
                condition=constraint.condition,
                include=constraint.include,
                unique=True,
            )
            if not expected_tail:
                # See _compare_indexes for why we skip the sentinel.
                continue
            missing_by_def.setdefault(expected_tail, []).append(constraint)

    for tail, m_list in missing_by_def.items():
        e_list = extra_by_def.get(tail)
        if e_list and len(m_list) == 1 and len(e_list) == 1:
            constraint = m_list[0]
            old_name = e_list[0]
            # Index-only uniques live as indexes, not constraints, so
            # emit IndexDrift so the planner uses ALTER INDEX RENAME.
            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    constraint_type=ConType.UNIQUE,
                    fields=list(constraint.fields),
                    issue=f"rename from {old_name}",
                    drift=IndexDrift(
                        kind=DriftKind.RENAMED,
                        table=table,
                        old_name=old_name,
                        new_name=constraint.name,
                    ),
                )
            )
            renamed_missing.add(constraint.name)
            renamed_extra.add(old_name)

    return statuses, renamed_missing, renamed_extra


def _detect_check_renames(
    cursor: CursorWrapper,
    missing: list[CheckConstraint],
    extra_names: list[str],
    actual_dict: dict[str, ConstraintState],
    model: type[Model],
    table: str,
) -> tuple[list[ConstraintStatus], set[str], set[str]]:
    """Match missing and extra check constraints by normalized definition."""
    statuses: list[ConstraintStatus] = []
    renamed_missing: set[str] = set()
    renamed_extra: set[str] = set()

    # Skip the round-trip normalization loop if there are no extras to
    # potentially match — the steady-state path with no drift.
    extra_by_def: dict[str, list[str]] = {}
    for name in extra_names:
        if definition := actual_dict[name].definition:
            extra_by_def.setdefault(definition, []).append(name)

    missing_by_def: dict[str, list[CheckConstraint]] = {}
    if extra_by_def:
        for constraint in missing:
            expected_def = _get_expected_check_definition(cursor, model, constraint)
            if not expected_def:
                # Normalization failed; bucketing under "" would conflate
                # multiple sentinel-failing constraints and disable rename
                # detection for the rest.
                continue
            missing_by_def.setdefault(expected_def, []).append(constraint)

    for definition, m_list in missing_by_def.items():
        e_list = extra_by_def.get(definition)
        if e_list and len(m_list) == 1 and len(e_list) == 1:
            constraint = m_list[0]
            old_name = e_list[0]
            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    constraint_type=ConType.CHECK,
                    fields=[],
                    issue=f"rename from {old_name}",
                    drift=ConstraintDrift(
                        kind=DriftKind.RENAMED,
                        table=table,
                        old_name=old_name,
                        new_name=constraint.name,
                    ),
                )
            )
            renamed_missing.add(constraint.name)
            renamed_extra.add(old_name)

    return statuses, renamed_missing, renamed_extra


def _compare_index_only_unique(
    cursor: CursorWrapper,
    model: type[Model],
    constraint: UniqueConstraint,
    actual_state: ConstraintState,
    table: str,
) -> tuple[str | None, ConstraintDrift | None]:
    """Compare an index-only unique constraint against the DB.

    Index-only variants (condition, expressions, opclasses) live as unique
    indexes in PostgreSQL, not pg_constraint rows.  Their ConstraintState
    comes from the pg_index query path with a pg_get_indexdef definition.
    """
    actual_def = actual_state.definition
    if not actual_def:
        return None, None

    issue = _compare_normalized_index(
        cursor=cursor,
        model=model,
        expressions=constraint.expressions,
        fields_orders=[(f, "") for f in constraint.fields],
        opclasses=list(constraint.opclasses),
        condition=constraint.condition,
        include=constraint.include,
        actual_def=actual_def,
        unique=True,
    )
    if issue:
        changed = ConstraintDrift(
            kind=DriftKind.CHANGED, table=table, constraint=constraint, model=model
        )
        return issue, changed

    return None, None


def _compare_normalized_index(
    *,
    cursor: CursorWrapper,
    model: type[Model],
    expressions: tuple[Expression | ReplaceableExpression, ...],
    fields_orders: list[tuple[str, str]],
    opclasses: list[str],
    condition: Q | None,
    include: tuple[str, ...] | None,
    actual_def: str,
    unique: bool = False,
) -> str | None:
    """Compare a model index/constraint against pg_get_indexdef text.

    Round-trips the model side through Postgres so both sides come from
    pg_get_indexdef, then string-compares the normalized `USING ...` bodies.

    Returns an issue string if definitions differ, None if they match.
    """
    expected_tail = _normalize_index_def(
        cursor,
        model,
        expressions=expressions,
        fields_orders=fields_orders,
        opclasses=opclasses,
        condition=condition,
        include=include,
        unique=unique,
    )
    actual_tail = _index_def_tail(actual_def)
    if not expected_tail:
        # Round-trip normalization couldn't complete (model SQL
        # incompatible with live shape). Report drift with the actual text;
        # the normalized model text is unavailable for the diagnostic.
        return f"definition differs: DB has {actual_tail!r}"

    if actual_tail != expected_tail:
        return (
            f"definition differs: DB has {actual_tail!r}, "
            f"model expects {expected_tail!r}"
        )
    return None


# Round-trip normalization: feed model-side SQL to Postgres on a
# session-private temp table, read back via pg_get_*.
_PROBE_TABLE = "_plain_convergence_probe"
_PROBE_CONSTRAINT = "_c"
_PROBE_INDEX = "_probe_ix"

# Errors raised by Postgres when the model SQL is incompatible with the live
# table shape (unmigrated column types, references to dropped columns, etc.).
# Helpers catch these and return "" so drift is still reported via inequality.
# DataError covers literal-cast mismatches (e.g. text default on int column);
# NotSupportedError covers the rare PG-side "this combination isn't allowed"
# rejection. Both are narrow enough that catching the parent class is fine.
# ProgrammingError is intentionally narrowed to specific 42xxx subclasses —
# privilege failures (InsufficientPrivilege, also a ProgrammingError) and
# plain-side syntax bugs must propagate so users get a clear diagnostic
# instead of silent drift noise.
_PROBE_FALLBACK_ERRORS: tuple[type[Exception], ...] = (
    psycopg.errors.UndefinedColumn,
    psycopg.errors.UndefinedFunction,
    psycopg.errors.UndefinedObject,
    psycopg.errors.UndefinedTable,
    psycopg.errors.InvalidColumnReference,
    psycopg.errors.InvalidObjectDefinition,
    psycopg.errors.InvalidTableDefinition,
    psycopg.errors.DatatypeMismatch,
    psycopg.errors.WrongObjectType,
    psycopg.errors.AmbiguousColumn,
    psycopg.errors.DataError,
    psycopg.errors.NotSupportedError,
)


class ReadOnlyConnectionError(RuntimeError):
    """Raised when convergence analysis runs on a read-only connection.

    Analysis normalizes the model side of each comparison by round-tripping
    SQL through a session-private temp table. That requires DDL, which is
    rejected on standby connections and inside `read_only()` blocks.
    """


_READ_ONLY_MESSAGE = (
    "Convergence analysis requires write access — it normalizes model SQL by "
    "creating a session-private temp table. The current connection rejected "
    "DDL (read-only transaction or standby). Run analysis against a "
    "primary/writable connection."
)


@dataclass
class _ProbeSession:
    """Reuse scope for one model's probe table (see `_probe_session`)."""

    model: type[Model]
    created: bool = False


# Set while `analyze_model` runs so the per-comparison probes share one temp
# table instead of creating and dropping one each. A single connection is
# single-threaded, but a ContextVar keeps the scope clean and never leaks the
# session if analysis raises.
_active_probe_session: contextvars.ContextVar[_ProbeSession | None] = (
    contextvars.ContextVar("active_probe_session", default=None)
)


@contextmanager
def _probe_session(cursor: CursorWrapper, model: type[Model]) -> Iterator[None]:
    """Reuse one probe table across every round-trip in a model's analysis.

    The temp table is created lazily by the first probe inside this scope and
    dropped once on exit, so a model with no expression/constraint round-trips
    creates nothing while a model with many shares a single table instead of
    churning one per comparison. The exit DROP runs only on the success path —
    on an error it's skipped to avoid dropping against an aborted connection, so
    the table can briefly outlive the analysis (autocommit commits the CREATE);
    the next analysis recreates it cleanly (see `_create_probe_table`).
    """
    session = _ProbeSession(model=model)
    token = _active_probe_session.set(session)
    try:
        yield
    finally:
        _active_probe_session.reset(token)
    if session.created:
        cursor.execute(f"DROP TABLE pg_temp.{_PROBE_TABLE}")


def _create_probe_table(cursor: CursorWrapper, model: type[Model]) -> None:
    """(Re)create the session-private probe table mirroring the model's real table.

    Drops any stale table of the same name first so a leak can't wedge analysis:
    the shipped CLI runs convergence in autocommit, so the CREATE commits before
    later probes run, and a non-fallback error escaping `analyze_model` would
    otherwise leave the table on a pooled connection to collide with the next
    run's CREATE. The
    DROP is schema-qualified to `pg_temp` so a real table sharing the name (in
    the user's own schema) can't be hit by mistake. Raises ReadOnlyConnectionError
    when the connection rejects the DDL.
    """
    table = quote_name(model.model_options.db_table)
    try:
        with cursor.connection.transaction():
            cursor.execute(f"DROP TABLE IF EXISTS pg_temp.{_PROBE_TABLE}")
            cursor.execute(f"CREATE TEMP TABLE {_PROBE_TABLE} (LIKE {table})")
    except psycopg.errors.ReadOnlySqlTransaction as exc:
        raise ReadOnlyConnectionError(_READ_ONLY_MESSAGE) from exc


@contextmanager
def _probe_table(cursor: CursorWrapper, model: type[Model]) -> Iterator[None]:
    """Provide an empty temp table mirroring the model's real table for one
    round-trip, isolating the probe's DDL so it can't leak into the analyze
    transaction.

    Inside an active `_probe_session` for the same model, the table is created
    once and reused: each probe runs in a SAVEPOINT that is always rolled back,
    undoing the probe's ADD/ALTER while leaving the shared table in place.
    Outside a session, the table is created and dropped for this one probe.

    `cursor.connection.transaction()` issues a SAVEPOINT when nested (or BEGIN in
    autocommit), so model SQL incompatible with the live column shape rolls back
    to this scope instead of poisoning the surrounding transaction; helpers catch
    the psycopg error and fall back to a sentinel.
    """
    session = _active_probe_session.get()
    if session is not None and session.model is model:
        # Reuse the session's shared table; `_probe_session` owns its lifetime.
        if not session.created:
            _create_probe_table(cursor, model)
            session.created = True
        drop_on_exit = False
    else:
        # No session: this probe owns the table for its lifetime.
        _create_probe_table(cursor, model)
        drop_on_exit = True

    try:
        with cursor.connection.transaction() as savepoint:
            yield
            # Probe read its definition; undo the ADD/ALTER but keep the table.
            # psycopg rolls the SAVEPOINT back without surfacing an error.
            raise psycopg.Rollback(savepoint)
    finally:
        if drop_on_exit:
            cursor.execute(f"DROP TABLE pg_temp.{_PROBE_TABLE}")


def _normalize_constraint_def(
    cursor: CursorWrapper, model: type[Model], constraint_clause: str
) -> str:
    """Round-trip a constraint clause through Postgres so both sides of the
    comparison are deparsed by pg_get_constraintdef — string equality then
    covers `IN` vs `= ANY (ARRAY[...])`, redundant parens, type cast drift,
    INCLUDE column ordering, etc.

    Returns "" if the model SQL is incompatible with the live table shape
    (e.g. unmigrated column-type drift). Drift still gets reported via the
    inequality with the actual live definition; only the normalized model
    text is omitted from the diagnostic.
    """
    try:
        with _probe_table(cursor, model):
            # Add as validated: the temp table is empty so the implicit scan is
            # instant. NOT VALID would leave a trailing " NOT VALID" suffix in
            # pg_get_constraintdef that the live constraint won't have.
            cursor.execute(
                f"ALTER TABLE {_PROBE_TABLE} "
                f"ADD CONSTRAINT {_PROBE_CONSTRAINT} {constraint_clause}"
            )
            cursor.execute(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "WHERE c.conname = %s "
                "AND c.conrelid = (SELECT oid FROM pg_class WHERE relname = %s "
                "AND relnamespace = pg_my_temp_schema())",
                [_PROBE_CONSTRAINT, _PROBE_TABLE],
            )
            row = cursor.fetchone()
            return row[0] if row else ""
    except _PROBE_FALLBACK_ERRORS:
        return ""


def _get_expected_check_definition(
    cursor: CursorWrapper, model: type[Model], constraint: CheckConstraint
) -> str:
    check_sql = compile_expression_sql(model, constraint.check)
    return _normalize_constraint_def(cursor, model, f"CHECK ({check_sql})")


def _normalize_index_def(
    cursor: CursorWrapper,
    model: type[Model],
    *,
    expressions: tuple[Expression | ReplaceableExpression, ...] = (),
    fields_orders: list[tuple[str, str]] | None = None,
    opclasses: list[str] | None = None,
    condition: Q | None = None,
    include: tuple[str, ...] | None = None,
    unique: bool = False,
) -> str:
    """Round-trip an index through Postgres and return its normalized body.

    Returns the `USING ... [INCLUDE (...)] [WHERE (...)]` tail of pg_get_indexdef,
    safe to compare directly against `_index_def_tail(actual_def)` from the
    DB side. The `CREATE [UNIQUE] INDEX <name> ON <table>` prefix is stripped
    here so callers don't have to.

    Returns "" if the model SQL is incompatible with the live table shape;
    comparison sites then see inequality and report drift without the
    normalized model text.
    """
    if expressions:
        columns_sql = compile_index_expressions_sql(model, expressions)
    else:
        col_parts: list[str] = []
        for i, (field_name, suffix) in enumerate(fields_orders or []):
            field = model._model_meta.get_forward_field(field_name)
            col = quote_name(field.column)
            if opclasses:
                col = f"{col} {opclasses[i]}"
            if suffix:
                col = f"{col} {suffix}"
            col_parts.append(col)
        columns_sql = ", ".join(col_parts)

    where_sql = ""
    if condition is not None:
        where_sql = f" WHERE ({compile_expression_sql(model, condition)})"
    include_sql = build_include_sql(model, include or ())
    create_kw = "CREATE UNIQUE INDEX" if unique else "CREATE INDEX"

    try:
        with _probe_table(cursor, model):
            cursor.execute(
                f"{create_kw} {_PROBE_INDEX} ON {_PROBE_TABLE} "
                f"({columns_sql}){include_sql}{where_sql}"
            )
            cursor.execute(
                "SELECT pg_get_indexdef(c.oid) FROM pg_class c "
                "WHERE c.relname = %s AND c.relnamespace = pg_my_temp_schema()",
                [_PROBE_INDEX],
            )
            row = cursor.fetchone()
            return _index_def_tail(row[0]) if row else ""
    except _PROBE_FALLBACK_ERRORS:
        return ""


def _index_def_tail(definition: str) -> str:
    """Strip the `CREATE [UNIQUE] INDEX <name> ON <schema>.<table>` prefix
    from a pg_get_indexdef output, leaving the normalized body that's safe to
    compare across different index names/tables."""
    using_pos = definition.find("USING ")
    return definition[using_pos:] if using_pos >= 0 else definition


def _get_expected_unique_definition(
    cursor: CursorWrapper, model: type[Model], constraint: UniqueConstraint
) -> str:
    """Normalized UNIQUE definition for the model's constraint, as Postgres
    prints it.

    PostgreSQL only stores field-based unique constraints (with optional
    INCLUDE and DEFERRABLE) in pg_constraint. Expression-based, conditional,
    and opclass constraints remain as indexes only — those are compared via
    the index-definition path.
    """
    columns_sql = ", ".join(
        quote_name(model._model_meta.get_forward_field(f).column)
        for f in constraint.fields
    )
    include_sql = build_include_sql(model, constraint.include)
    defer_sql = deferrable_sql(constraint.deferrable)
    clause = f"UNIQUE ({columns_sql}){include_sql}{defer_sql}"
    return _normalize_constraint_def(cursor, model, clause)

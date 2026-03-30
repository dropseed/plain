from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
from typing import TYPE_CHECKING, Any

from ..constraints import CheckConstraint, UniqueConstraint
from ..dialect import quote_name
from ..fields.related import ForeignKeyField
from ..indexes import Index
from ..introspection import (
    ConstraintState,
    ForeignKeyState,
    TableState,
    introspect_table,
    normalize_check_definition,
    normalize_index_definition,
    normalize_unique_definition,
)

if TYPE_CHECKING:
    from ..base import Model
    from ..connection import DatabaseConnection
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

    def describe(self) -> str:
        match self.kind:
            case DriftKind.MISSING:
                return f"{self.table}: FK {self.name} missing ({self.column} → {self.target_table}.{self.target_column})"
            case DriftKind.UNVALIDATED:
                return f"{self.table}: FK {self.name} NOT VALID"
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


type Drift = IndexDrift | ConstraintDrift | ForeignKeyDrift | NullabilityDrift


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
    drift: NullabilityDrift | None = None


@dataclass
class IndexStatus:
    name: str
    fields: list[str] = field(default_factory=list)
    issue: str | None = None
    drift: IndexDrift | None = None


@dataclass
class ConstraintStatus:
    name: str
    type: str
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

    @cached_property
    def drifts(self) -> list[Drift]:
        """All detected schema drifts."""
        result: list[Drift] = []
        for col in self.columns:
            if col.drift:
                result.append(col.drift)
        for idx in self.indexes:
            if idx.drift:
                result.append(idx.drift)
        for con in self.constraints:
            if con.drift:
                result.append(con.drift)
        return result

    @cached_property
    def issue_count(self) -> int:
        """Total issues (table + columns + indexes + constraints)."""
        count = len(self.table_issues)
        count += sum(1 for col in self.columns if col.issue)
        count += sum(1 for idx in self.indexes if idx.issue)
        count += sum(1 for con in self.constraints if con.issue)
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
                    "drift": col.drift.describe() if col.drift else None,
                }
                for col in self.columns
            ],
            "indexes": [
                {
                    "name": idx.name,
                    "fields": idx.fields,
                    "issue": idx.issue,
                    "drift": idx.drift.describe() if idx.drift else None,
                }
                for idx in self.indexes
            ],
            "constraints": [
                {
                    "name": con.name,
                    "type": con.type,
                    "fields": con.fields,
                    "issue": con.issue,
                    "drift": con.drift.describe() if con.drift else None,
                }
                for con in self.constraints
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

    return ModelAnalysis(
        label=model.model_options.label,
        table=table_name,
        columns=_compare_columns(model, db, table_name, cursor),
        indexes=_compare_indexes(model, db, table_name),
        constraints=_compare_constraints(model, db, table_name),
    )


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
        db_type = f.db_type()
        if db_type is None:
            continue

        expected_col_names.add(f.column)
        issue: str | None = None
        drift: NullabilityDrift | None = None

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
                drift = NullabilityDrift(
                    table=table,
                    column=f.column,
                    model_allows_null=False,
                    has_null_rows=has_nulls,
                )
            elif f.allow_null and actual.not_null:
                issue = "expected NULL, actual NOT NULL"
                drift = NullabilityDrift(
                    table=table,
                    column=f.column,
                    model_allows_null=True,
                )

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
                drift=drift,
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


# Index comparison with rename detection


def _compare_indexes(
    model: type[Model], db: TableState, table: str
) -> list[IndexStatus]:
    statuses: list[IndexStatus] = []
    missing: list[Index] = []
    model_index_names = {idx.name for idx in model.model_options.indexes}

    for index in model.model_options.indexes:
        if index.name not in db.indexes:
            missing.append(index)
            continue

        db_idx = db.indexes[index.name]

        if not db_idx.valid:
            statuses.append(
                IndexStatus(
                    name=index.name,
                    fields=list(index.fields) if index.fields else [],
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
            expected_def = normalize_index_definition(index.to_sql(model))
            actual_def = normalize_index_definition(db_idx.definition)
            if expected_def != actual_def:
                if index.fields:
                    expected_columns = [
                        model._model_meta.get_forward_field(field_name).column
                        for field_name in index.fields
                    ]
                    issue = (
                        f"columns differ: DB has {db_idx.columns}, model expects {expected_columns}"
                        if expected_columns != db_idx.columns
                        else f"definition differs: DB has {db_idx.definition!r}"
                    )
                else:
                    issue = f"definition differs: DB has {db_idx.definition!r}"
                statuses.append(
                    IndexStatus(
                        name=index.name,
                        fields=list(index.fields) if index.fields else [],
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
                fields=list(index.fields) if index.fields else [],
            )
        )

    # Extra indexes (in DB but not in model)
    extra_names = sorted(db.indexes.keys() - model_index_names)

    # Detect renames: match missing and extra by normalized definition
    renamed_missing: set[str] = set()
    renamed_extra: set[str] = set()

    missing_by_def: dict[str, list[Index]] = {}
    for index in missing:
        norm = normalize_index_definition(index.to_sql(model))
        missing_by_def.setdefault(norm, []).append(index)

    extra_by_def: dict[str, list[str]] = {}
    for name in extra_names:
        defn = db.indexes[name].definition
        if defn:
            norm = normalize_index_definition(defn)
            extra_by_def.setdefault(norm, []).append(name)

    for norm, m_list in missing_by_def.items():
        e_list = extra_by_def.get(norm)
        if e_list and len(m_list) == 1 and len(e_list) == 1:
            index = m_list[0]
            old_name = e_list[0]
            statuses.append(
                IndexStatus(
                    name=index.name,
                    fields=list(index.fields) if index.fields else [],
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
                    fields=list(index.fields) if index.fields else [],
                    issue="missing from database",
                    drift=IndexDrift(
                        kind=DriftKind.MISSING,
                        table=table,
                        index=index,
                        model=model,
                    ),
                )
            )

    # Remaining unmatched extra
    for name in extra_names:
        if name not in renamed_extra:
            statuses.append(
                IndexStatus(
                    name=name,
                    fields=db.indexes[name].columns,
                    issue="not in model",
                    drift=IndexDrift(
                        kind=DriftKind.UNDECLARED,
                        table=table,
                        name=name,
                    ),
                )
            )

    return statuses


# Constraint comparison


def _compare_constraints(
    model: type[Model], db: TableState, table: str
) -> list[ConstraintStatus]:
    statuses: list[ConstraintStatus] = []
    statuses.extend(_compare_unique_constraints(model, db, table))
    statuses.extend(_compare_check_constraints(model, db, table))
    statuses.extend(_compare_foreign_keys(model, db, table))
    return statuses


def _compare_unique_constraints(
    model: type[Model], db: TableState, table: str
) -> list[ConstraintStatus]:
    statuses: list[ConstraintStatus] = []
    actual = db.unique_constraints
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
                model, constraint, actual[constraint.name], table
            )
        elif actual_def := actual[constraint.name].definition:
            expected_def = _get_expected_unique_definition(model, constraint)
            if normalize_unique_definition(actual_def) != normalize_unique_definition(
                expected_def
            ):
                issue = f"definition differs: DB has {actual_def!r}, model expects {expected_def!r}"
                drift = ConstraintDrift(
                    kind=DriftKind.CHANGED,
                    table=table,
                    constraint=constraint,
                    model=model,
                )

        statuses.append(
            ConstraintStatus(
                name=constraint.name,
                type="unique",
                fields=list(constraint.fields),
                issue=issue,
                drift=drift,
            )
        )

    # Detect renames by columns
    rename_statuses, renamed_missing, renamed_extra = _detect_unique_renames(
        missing, extra_names, actual, model, table
    )
    statuses.extend(rename_statuses)

    for constraint in missing:
        if constraint.name not in renamed_missing:
            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    type="unique",
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
            if actual[name].from_index:
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
                    type="unique",
                    fields=actual[name].columns,
                    issue="not in model",
                    drift=undeclared_drift,
                )
            )

    return statuses


def _compare_check_constraints(
    model: type[Model], db: TableState, table: str
) -> list[ConstraintStatus]:
    statuses: list[ConstraintStatus] = []
    actual = db.check_constraints
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
            expected_def = _get_expected_check_definition(model, constraint)
            if normalize_check_definition(actual_def) != normalize_check_definition(
                expected_def
            ):
                issue = f"definition differs: DB has {actual_def!r}, model expects {expected_def!r}"
                drift = ConstraintDrift(
                    kind=DriftKind.CHANGED,
                    table=table,
                    constraint=constraint,
                    model=model,
                )

        statuses.append(
            ConstraintStatus(
                name=constraint.name,
                type="check",
                fields=[],
                issue=issue,
                drift=drift,
            )
        )

    # Detect renames by definition
    rename_statuses, renamed_missing, renamed_extra = _detect_check_renames(
        missing, extra_names, actual, model, table
    )
    statuses.extend(rename_statuses)

    for constraint in missing:
        if constraint.name not in renamed_missing:
            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    type="check",
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
                    type="check",
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

    # Build expected FKs from model fields: shape → (field_name, constraint_name)
    expected_fks: dict[tuple[str, str, str], tuple[str, str]] = {}
    for f in model._model_meta.local_fields:
        if isinstance(f, ForeignKeyField) and f.db_constraint:
            assert f.name is not None
            to_table = f.target_field.model.model_options.db_table
            to_column = f.target_field.column
            constraint_name = generate_fk_constraint_name(
                table, f.column, to_table, to_column
            )
            expected_fks[(f.column, to_table, to_column)] = (f.name, constraint_name)

    # Build actual FKs from DB: shape → (constraint_name, ForeignKeyState)
    actual_fk_by_shape: dict[tuple[str, str, str], tuple[str, ForeignKeyState]] = {}
    for name, fk in db.foreign_keys.items():
        actual_fk_by_shape[(fk.column, fk.target_table, fk.target_column)] = (name, fk)

    matched_fk_names: set[str] = set()
    for key, (field_name, constraint_name) in expected_fks.items():
        if match := actual_fk_by_shape.get(key):
            actual_name, fk_state = match
            matched_fk_names.add(actual_name)

            # Check validation state
            issue: str | None = None
            drift: ForeignKeyDrift | None = None
            if not fk_state.validated:
                issue = "NOT VALID — needs validation"
                drift = ForeignKeyDrift(
                    kind=DriftKind.UNVALIDATED,
                    table=table,
                    name=actual_name,
                )

            statuses.append(
                ConstraintStatus(
                    name=actual_name,
                    type="fk",
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
                    type="fk",
                    fields=[col],
                    issue="missing from database",
                    drift=ForeignKeyDrift(
                        kind=DriftKind.MISSING,
                        table=table,
                        name=constraint_name,
                        column=col,
                        target_table=to_table,
                        target_column=to_column,
                    ),
                )
            )

    for name in sorted(db.foreign_keys.keys() - matched_fk_names):
        fk = db.foreign_keys[name]
        statuses.append(
            ConstraintStatus(
                name=name,
                type="fk",
                fields=[fk.column],
                issue=f"not in model (→ {fk.target_table}.{fk.target_column})",
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
    missing: list[UniqueConstraint],
    extra_names: list[str],
    actual_dict: dict[str, ConstraintState],
    model: type[Model],
    table: str,
) -> tuple[list[ConstraintStatus], set[str], set[str]]:
    """Match missing and extra unique constraints by structure.

    Constraint-backed (not index_only): matched by resolved column tuple.
    Index-only (condition/expression/opclass): matched by normalized index
    definition, which captures the full semantics including WHERE clauses,
    opclasses, and expressions.
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
                if not old_def or normalize_index_definition(
                    old_def
                ) != normalize_index_definition(constraint.to_sql(model)):
                    continue
            DriftType = IndexDrift if constraint.index_only else ConstraintDrift
            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    type="unique",
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

    # Phase 2: Expression-based — match by normalized index definition.
    missing_by_def: dict[str, list[UniqueConstraint]] = {}
    for constraint in missing:
        if constraint.fields or constraint.name in renamed_missing:
            continue
        norm = normalize_index_definition(constraint.to_sql(model))
        missing_by_def.setdefault(norm, []).append(constraint)

    extra_by_def: dict[str, list[str]] = {}
    for name in extra_names:
        if name in renamed_extra:
            continue
        defn = actual_dict[name].definition
        if defn:
            norm = normalize_index_definition(defn)
            extra_by_def.setdefault(norm, []).append(name)

    for norm, m_list in missing_by_def.items():
        e_list = extra_by_def.get(norm)
        if e_list and len(m_list) == 1 and len(e_list) == 1:
            constraint = m_list[0]
            old_name = e_list[0]
            # Index-only uniques live as indexes, not constraints, so
            # emit IndexDrift so the planner uses ALTER INDEX RENAME.
            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    type="unique",
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

    missing_by_def: dict[str, list[CheckConstraint]] = {}
    for constraint in missing:
        expected_def = _get_expected_check_definition(model, constraint)
        norm = normalize_check_definition(expected_def)
        missing_by_def.setdefault(norm, []).append(constraint)

    extra_by_def: dict[str, list[str]] = {}
    for name in extra_names:
        if definition := actual_dict[name].definition:
            norm = normalize_check_definition(definition)
            extra_by_def.setdefault(norm, []).append(name)

    for norm_def, m_list in missing_by_def.items():
        e_list = extra_by_def.get(norm_def)
        if e_list and len(m_list) == 1 and len(e_list) == 1:
            constraint = m_list[0]
            old_name = e_list[0]
            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    type="check",
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
    model: type[Model],
    constraint: UniqueConstraint,
    actual_state: ConstraintState,
    table: str,
) -> tuple[str | None, ConstraintDrift | None]:
    """Compare an index-only unique constraint against the DB.

    Index-only variants (condition, expressions, opclasses) live as unique
    indexes in PostgreSQL, not pg_constraint rows.  Their ConstraintState
    comes from the pg_index query path with a pg_get_indexdef definition.

    For expression-based constraints we compare normalized index definitions.
    For field-based (condition/opclass) we parse pg_get_indexdef into
    structured components and compare each, avoiding fragile cross-format
    SQL normalization between the ORM and PostgreSQL.
    """
    actual_def = actual_state.definition
    if not actual_def:
        return None, None

    changed = ConstraintDrift(
        kind=DriftKind.CHANGED, table=table, constraint=constraint, model=model
    )

    if constraint.expressions:
        # Expression-based: the expression IS the core structure, so
        # normalized-definition comparison is the right tool.
        expected_def = constraint.to_sql(model)
        if normalize_index_definition(actual_def) != normalize_index_definition(
            expected_def
        ):
            return f"definition differs: DB has {actual_def!r}", changed
    else:
        # Field-based with condition/opclasses: compare structured components
        # parsed from pg_get_indexdef rather than normalizing full SQL strings.
        db_parts = _parse_index_definition(actual_def)
        expected_columns = [
            model._model_meta.get_forward_field(f).column for f in constraint.fields
        ]
        if db_parts.columns != expected_columns:
            return (
                f"columns differ: DB has {db_parts.columns}, model expects {expected_columns}",
                changed,
            )
        expected_opclasses = list(constraint.opclasses) if constraint.opclasses else []
        if db_parts.opclasses != expected_opclasses:
            return (
                f"opclasses differ: DB has {db_parts.opclasses}, model expects {expected_opclasses}",
                changed,
            )
        has_condition = constraint.condition is not None
        if has_condition != db_parts.has_where:
            where_desc = "has WHERE" if db_parts.has_where else "no WHERE"
            return (
                f"condition differs: DB {where_desc}, model {'has' if has_condition else 'no'} condition",
                changed,
            )
        if has_condition and db_parts.where_clause:
            from ..ddl import compile_expression_sql

            assert constraint.condition is not None
            expected_where = compile_expression_sql(model, constraint.condition)
            if normalize_check_definition(
                db_parts.where_clause
            ) != normalize_check_definition(expected_where):
                return (
                    f"condition differs: DB has WHERE ({db_parts.where_clause})",
                    changed,
                )

    return None, None


@dataclass
class _IndexParts:
    """Structured components parsed from pg_get_indexdef output."""

    columns: list[str]
    opclasses: list[str]
    has_where: bool
    where_clause: str | None


def _parse_index_definition(definition: str) -> _IndexParts:
    """Parse pg_get_indexdef output into structured components.

    Extracts columns, opclasses, and WHERE clause from definitions like:
      CREATE UNIQUE INDEX name ON schema.table USING btree (col1, col2 opclass) WHERE (condition)
    """
    s = definition.lower().replace('"', "")

    # Extract WHERE clause (everything after WHERE keyword)
    where_clause = None
    has_where = False
    where_match = re.search(r"\bwhere\s*\(", s)
    if where_match:
        has_where = True
        # Extract the balanced WHERE expression
        start = where_match.end() - 1  # include the opening paren
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
                if depth == 0:
                    where_clause = s[start + 1 : i].strip()
                    s = s[: where_match.start()].strip()
                    break

    # Find the column list: content between parens after USING method
    columns: list[str] = []
    opclasses: list[str] = []
    using_match = re.search(r"\busing\s+\w+\s*\(", s)
    if using_match:
        start = using_match.end()
        depth = 1
        for i in range(start, len(s)):
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
                if depth == 0:
                    col_str = s[start:i].strip()
                    for part in col_str.split(","):
                        part = part.strip()
                        # "col opclass" or just "col"
                        tokens = part.split()
                        if tokens:
                            columns.append(tokens[0])
                            opclasses.append(tokens[1] if len(tokens) > 1 else "")
                    break

    # Strip empty opclasses if none are set
    if all(oc == "" for oc in opclasses):
        opclasses = []

    return _IndexParts(
        columns=columns,
        opclasses=opclasses,
        has_where=has_where,
        where_clause=where_clause,
    )


def _get_expected_check_definition(
    model: type[Model], constraint: CheckConstraint
) -> str:
    """Generate the CHECK expression that the model would produce."""
    from ..ddl import compile_expression_sql

    check_sql = compile_expression_sql(model, constraint.check)
    return f"CHECK ({check_sql})"


def _get_expected_unique_definition(
    model: type[Model], constraint: UniqueConstraint
) -> str:
    """Generate the UNIQUE definition in pg_get_constraintdef format.

    PostgreSQL only stores field-based unique constraints (with optional
    INCLUDE and DEFERRABLE) in pg_constraint. Expression-based, conditional,
    and opclass constraints cannot be attached as constraints — they remain
    as indexes only.
    """
    from ..ddl import build_include_sql, deferrable_sql

    columns_sql = ", ".join(
        quote_name(model._model_meta.get_forward_field(f).column)
        for f in constraint.fields
    )
    include_sql = build_include_sql(model, constraint.include)
    defer_sql = deferrable_sql(constraint.deferrable)
    return f"UNIQUE ({columns_sql}){include_sql}{defer_sql}"

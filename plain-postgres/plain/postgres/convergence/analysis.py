from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any

from ..constraints import CheckConstraint, UniqueConstraint
from ..db import get_connection
from ..fields.related import ForeignKeyField
from ..indexes import Index
from ..introspection import (
    ConstraintState,
    TableState,
    introspect_table,
    normalize_check_definition,
)
from ..registry import models_registry
from .fixes import (
    AddConstraintFix,
    CreateIndexFix,
    DropConstraintFix,
    DropIndexFix,
    Fix,
    RebuildConstraintFix,
    RebuildIndexFix,
    RenameConstraintFix,
    RenameIndexFix,
    ValidateConstraintFix,
)

if TYPE_CHECKING:
    from ..base import Model
    from ..connection import DatabaseConnection
    from ..utils import CursorWrapper


@dataclass
class ColumnStatus:
    name: str
    field_name: str
    type: str
    nullable: bool
    primary_key: bool
    pk_suffix: str
    issue: str | None = None


@dataclass
class IndexStatus:
    name: str
    fields: list[str] = field(default_factory=list)
    issue: str | None = None
    fix: Fix | None = None


@dataclass
class ConstraintStatus:
    name: str
    type: str
    fields: list[str] = field(default_factory=list)
    issue: str | None = None
    fix: Fix | None = None


@dataclass
class ModelAnalysis:
    label: str
    table: str
    table_issues: list[str] = field(default_factory=list)
    columns: list[ColumnStatus] = field(default_factory=list)
    indexes: list[IndexStatus] = field(default_factory=list)
    constraints: list[ConstraintStatus] = field(default_factory=list)

    @cached_property
    def fixes(self) -> list[Fix]:
        """All auto-fixes, sorted by pass_order."""
        result: list[Fix] = []
        for idx in self.indexes:
            if idx.fix:
                result.append(idx.fix)
        for con in self.constraints:
            if con.fix:
                result.append(con.fix)
        result.sort(key=lambda f: f.pass_order)
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
                }
                for col in self.columns
            ],
            "indexes": [
                {
                    "name": idx.name,
                    "fields": idx.fields,
                    "issue": idx.issue,
                    "fix": idx.fix.describe() if idx.fix else None,
                }
                for idx in self.indexes
            ],
            "constraints": [
                {
                    "name": con.name,
                    "type": con.type,
                    "fields": con.fields,
                    "issue": con.issue,
                    "fix": con.fix.describe() if con.fix else None,
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
    issue (if any) and Fix object (if auto-fixable).
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
        columns=_compare_columns(model, db),
        indexes=_compare_indexes(model, db, table_name),
        constraints=_compare_constraints(model, db, table_name),
    )


def detect_fixes() -> list[Fix]:
    """Scan all models against the database and return fixes in pass order."""
    conn = get_connection()
    fixes: list[Fix] = []

    with conn.cursor() as cursor:
        for model in models_registry.get_models():
            fixes.extend(analyze_model(conn, cursor, model).fixes)

    fixes.sort(key=lambda f: f.pass_order)
    return fixes


def detect_model_fixes(
    conn: DatabaseConnection, cursor: CursorWrapper, model: type[Model]
) -> list[Fix]:
    """Detect fixes for a single model."""
    return analyze_model(conn, cursor, model).fixes


# Column comparison


def _compare_columns(model: type[Model], db: TableState) -> list[ColumnStatus]:
    statuses: list[ColumnStatus] = []
    expected_col_names: set[str] = set()

    for f in model._model_meta.local_fields:
        db_type = f.db_type()
        if db_type is None:
            continue

        expected_col_names.add(f.column)
        issue: str | None = None

        if f.column not in db.columns:
            issue = "missing from database"
        else:
            actual = db.columns[f.column]
            if db_type != actual.type:
                issue = f"expected {db_type}, actual {actual.type}"
            elif (not f.allow_null) != actual.not_null:
                exp = "NOT NULL" if not f.allow_null else "NULL"
                act = "NOT NULL" if actual.not_null else "NULL"
                issue = f"expected {exp}, actual {act}"

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
                    fix=RebuildIndexFix(table, index, model),
                )
            )
            continue

        # Check if columns match
        if index.fields:
            expected_columns = [
                model._model_meta.get_forward_field(field_name).column
                for field_name in index.fields
            ]
            if expected_columns != db_idx.columns:
                statuses.append(
                    IndexStatus(
                        name=index.name,
                        fields=list(index.fields),
                        issue=f"columns differ: DB has {db_idx.columns}, model expects {expected_columns}",
                        fix=RebuildIndexFix(table, index, model),
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

    # Detect renames: cross-reference missing and extra by resolved columns
    missing_by_cols: dict[tuple[str, ...], list[Index]] = {}
    for index in missing:
        if not index.fields:
            continue
        cols = tuple(
            model._model_meta.get_forward_field(field_name).column
            for field_name in index.fields
        )
        missing_by_cols.setdefault(cols, []).append(index)

    extra_by_cols: dict[tuple[str, ...], list[str]] = {}
    for name in extra_names:
        cols = tuple(db.indexes[name].columns)
        if not cols:
            continue
        extra_by_cols.setdefault(cols, []).append(name)

    renamed_missing: set[str] = set()
    renamed_extra: set[str] = set()

    for cols, missing_list in missing_by_cols.items():
        extra_list = extra_by_cols.get(cols)
        if extra_list and len(missing_list) == 1 and len(extra_list) == 1:
            index = missing_list[0]
            old_name = extra_list[0]
            statuses.append(
                IndexStatus(
                    name=index.name,
                    fields=list(index.fields),
                    issue=f"rename from {old_name}",
                    fix=RenameIndexFix(table, old_name, index.name),
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
                    fix=CreateIndexFix(table, index, model),
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
                    fix=DropIndexFix(table, name),
                )
            )

    return statuses


# Constraint comparison


def _compare_constraints(
    model: type[Model], db: TableState, table: str
) -> list[ConstraintStatus]:
    statuses: list[ConstraintStatus] = []

    # Check and unique constraints (matched by name, with rename detection)
    for constraint_cls, constraint_type, actual_dict in [
        (UniqueConstraint, "unique", db.unique_constraints),
        (CheckConstraint, "check", db.check_constraints),
    ]:
        model_constraints = [
            c for c in model.model_options.constraints if isinstance(c, constraint_cls)
        ]
        expected_names = {c.name for c in model_constraints}
        extra_names = sorted(actual_dict.keys() - expected_names)

        missing: list[UniqueConstraint | CheckConstraint] = []
        for constraint in model_constraints:
            if constraint.name not in actual_dict:
                missing.append(constraint)
                continue

            issue: str | None = None
            fix: Fix | None = None

            if not actual_dict[constraint.name].validated:
                issue = "NOT VALID — needs validation"
                fix = ValidateConstraintFix(table, constraint.name)
            elif (
                constraint_type == "check"
                and isinstance(constraint, CheckConstraint)
                and (actual_def := actual_dict[constraint.name].definition)
            ):
                expected_def = _get_expected_check_definition(model, constraint)
                if normalize_check_definition(actual_def) != normalize_check_definition(
                    expected_def
                ):
                    issue = f"definition differs: DB has {actual_def!r}, model expects {expected_def!r}"
                    fix = RebuildConstraintFix(table, constraint, model)

            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    type=constraint_type,
                    fields=list(getattr(constraint, "fields", None) or []),
                    issue=issue,
                    fix=fix,
                )
            )

        # Detect renames: cross-reference missing and extra by structure
        if constraint_type == "unique":
            rename_statuses, renamed_missing, renamed_extra = _detect_unique_renames(
                missing, extra_names, actual_dict, model, table
            )
        elif constraint_type == "check":
            rename_statuses, renamed_missing, renamed_extra = _detect_check_renames(
                missing, extra_names, actual_dict, model, table
            )
        else:
            rename_statuses, renamed_missing, renamed_extra = [], set(), set()
        statuses.extend(rename_statuses)

        # Remaining unmatched missing → AddConstraintFix
        for constraint in missing:
            if constraint.name not in renamed_missing:
                statuses.append(
                    ConstraintStatus(
                        name=constraint.name,
                        type=constraint_type,
                        fields=list(getattr(constraint, "fields", None) or []),
                        issue="missing from database",
                        fix=AddConstraintFix(table, constraint, model),
                    )
                )

        # Remaining unmatched extra → DropConstraintFix
        for name in extra_names:
            if name not in renamed_extra:
                statuses.append(
                    ConstraintStatus(
                        name=name,
                        type=constraint_type,
                        fields=actual_dict[name].columns,
                        issue="not in model",
                        fix=DropConstraintFix(table, name),
                    )
                )

    # Foreign key constraints (matched by shape, not name)
    expected_fks: dict[tuple[str, str, str], str] = {}
    for f in model._model_meta.local_fields:
        if isinstance(f, ForeignKeyField) and f.db_constraint:
            assert f.name is not None
            to_table = f.target_field.model.model_options.db_table
            to_column = f.target_field.column
            expected_fks[(f.column, to_table, to_column)] = f.name

    actual_fk_by_shape: dict[tuple[str, str, str], str] = {}
    for name, fk in db.foreign_keys.items():
        actual_fk_by_shape[(fk.column, fk.target_table, fk.target_column)] = name

    matched_fk_names: set[str] = set()
    for key, field_name in expected_fks.items():
        if actual_name := actual_fk_by_shape.get(key):
            matched_fk_names.add(actual_name)
        else:
            col, to_table, to_column = key
            statuses.append(
                ConstraintStatus(
                    name=f"{field_name} → {to_table}.{to_column}",
                    type="fk",
                    fields=[col],
                    issue="missing from database",
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
            )
        )

    return statuses


def _detect_unique_renames(
    missing: list[UniqueConstraint | CheckConstraint],
    extra_names: list[str],
    actual_dict: dict[str, ConstraintState],
    model: type[Model],
    table: str,
) -> tuple[list[ConstraintStatus], set[str], set[str]]:
    """Match missing and extra unique constraints by resolved column tuple."""
    statuses: list[ConstraintStatus] = []
    renamed_missing: set[str] = set()
    renamed_extra: set[str] = set()

    missing_by_cols: dict[
        tuple[str, ...], list[UniqueConstraint | CheckConstraint]
    ] = {}
    for constraint in missing:
        fields = getattr(constraint, "fields", None)
        if not fields:
            continue
        cols = tuple(
            model._model_meta.get_forward_field(field_name).column
            for field_name in fields
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
            statuses.append(
                ConstraintStatus(
                    name=constraint.name,
                    type="unique",
                    fields=list(getattr(constraint, "fields", None) or []),
                    issue=f"rename from {old_name}",
                    fix=RenameConstraintFix(table, old_name, constraint.name),
                )
            )
            renamed_missing.add(constraint.name)
            renamed_extra.add(old_name)

    return statuses, renamed_missing, renamed_extra


def _detect_check_renames(
    missing: list[UniqueConstraint | CheckConstraint],
    extra_names: list[str],
    actual_dict: dict[str, ConstraintState],
    model: type[Model],
    table: str,
) -> tuple[list[ConstraintStatus], set[str], set[str]]:
    """Match missing and extra check constraints by normalized definition."""
    statuses: list[ConstraintStatus] = []
    renamed_missing: set[str] = set()
    renamed_extra: set[str] = set()

    missing_by_def: dict[str, list[UniqueConstraint | CheckConstraint]] = {}
    for constraint in missing:
        if not isinstance(constraint, CheckConstraint):
            continue
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
                    fix=RenameConstraintFix(table, old_name, constraint.name),
                )
            )
            renamed_missing.add(constraint.name)
            renamed_extra.add(old_name)

    return statuses, renamed_missing, renamed_extra


def _get_expected_check_definition(
    model: type[Model], constraint: CheckConstraint
) -> str:
    """Generate the CHECK expression that the model would produce."""
    from ..ddl import compile_expression_sql

    check_sql = compile_expression_sql(model, constraint.check)
    return f"CHECK ({check_sql})"

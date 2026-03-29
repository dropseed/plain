from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any

from ..constraints import BaseConstraint
from ..db import get_connection
from ..indexes import Index
from ..introspection import (
    IndexInfo,
    ModelSchemaResult,
    check_model,
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
    """Analyze a model's schema and produce enriched results with fixes.

    Wraps check_model() to classify each schema difference as auto-fixable
    (with a Fix object) or unfixable (needs a migration). Also detects
    index renames by cross-referencing missing and extra indexes by columns.
    """
    result = check_model(conn, cursor, model)
    table = result["table"]

    analysis = ModelAnalysis(
        label=result["label"],
        table=table,
        table_issues=[issue["detail"] for issue in result["issues"]],
    )

    # Columns — never auto-fixable
    for col in result["columns"]:
        issues = col["issues"]
        analysis.columns.append(
            ColumnStatus(
                name=col["name"],
                field_name=col["field_name"],
                type=col["type"],
                nullable=col["nullable"],
                primary_key=col["primary_key"],
                pk_suffix=col["pk_suffix"],
                issue=issues[0]["detail"] if issues else None,
            )
        )

    # Indexes — with rename detection
    analysis.indexes = _analyze_indexes(result, model, table)

    # Constraints
    analysis.constraints = _analyze_constraints(result, model, table)

    return analysis


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


def _analyze_indexes(
    result: ModelSchemaResult, model: type[Model], table: str
) -> list[IndexStatus]:
    """Process raw index issues into IndexStatus objects with fixes.

    Detects renames by cross-referencing missing and extra indexes that
    share the same columns.
    """
    statuses: list[IndexStatus] = []

    # Partition indexes by issue kind
    missing: list[tuple[IndexInfo, Index]] = []
    extra: list[IndexInfo] = []

    for idx in result["indexes"]:
        issues = idx["issues"]
        if not issues:
            statuses.append(IndexStatus(name=idx["name"], fields=idx["fields"]))
            continue

        kind = issues[0]["kind"]

        if kind == "index_missing":
            index_obj = _find_model_index(model, idx["name"])
            if index_obj:
                missing.append((idx, index_obj))
            else:
                statuses.append(
                    IndexStatus(
                        name=idx["name"],
                        fields=idx["fields"],
                        issue=issues[0]["detail"],
                    )
                )

        elif kind in ("index_invalid", "index_definition_changed"):
            index_obj = _find_model_index(model, idx["name"])
            fix = RebuildIndexFix(table, index_obj, model) if index_obj else None
            statuses.append(
                IndexStatus(
                    name=idx["name"],
                    fields=idx["fields"],
                    issue=issues[0]["detail"],
                    fix=fix,
                )
            )

        elif kind == "index_extra":
            extra.append(idx)

        else:
            statuses.append(
                IndexStatus(
                    name=idx["name"],
                    fields=idx["fields"],
                    issue=issues[0]["detail"],
                )
            )

    # Detect renames: cross-reference missing and extra by resolved columns
    missing_by_cols: dict[tuple[str, ...], list[tuple[IndexInfo, Index]]] = {}
    for idx, index_obj in missing:
        if not index_obj.fields:
            continue  # skip expression-based indexes
        cols = tuple(
            model._model_meta.get_forward_field(field_name).column
            for field_name in index_obj.fields
        )
        missing_by_cols.setdefault(cols, []).append((idx, index_obj))

    extra_by_cols: dict[tuple[str, ...], list[IndexInfo]] = {}
    for idx in extra:
        cols = tuple(idx["fields"])
        if not cols:
            continue  # skip expression-based indexes
        extra_by_cols.setdefault(cols, []).append(idx)

    renamed_missing_names: set[str] = set()
    renamed_extra_names: set[str] = set()

    for cols, missing_list in missing_by_cols.items():
        extra_list = extra_by_cols.get(cols)
        if extra_list and len(missing_list) == 1 and len(extra_list) == 1:
            _, index_obj = missing_list[0]
            extra_idx = extra_list[0]
            old_name = extra_idx["name"]
            new_name = index_obj.name
            statuses.append(
                IndexStatus(
                    name=new_name,
                    fields=list(index_obj.fields),
                    issue=f"rename from {old_name}",
                    fix=RenameIndexFix(table, old_name, new_name),
                )
            )
            renamed_missing_names.add(new_name)
            renamed_extra_names.add(old_name)

    # Remaining unmatched missing → CreateIndexFix
    for idx, index_obj in missing:
        if index_obj.name not in renamed_missing_names:
            statuses.append(
                IndexStatus(
                    name=idx["name"],
                    fields=idx["fields"],
                    issue="missing from database",
                    fix=CreateIndexFix(table, index_obj, model),
                )
            )

    # Remaining unmatched extra → DropIndexFix
    for idx in extra:
        if idx["name"] not in renamed_extra_names:
            statuses.append(
                IndexStatus(
                    name=idx["name"],
                    fields=idx["fields"],
                    issue="not in model",
                    fix=DropIndexFix(table, idx["name"]),
                )
            )

    return statuses


# Constraint analysis


def _analyze_constraints(
    result: ModelSchemaResult, model: type[Model], table: str
) -> list[ConstraintStatus]:
    """Process raw constraint issues into ConstraintStatus objects with fixes."""
    statuses: list[ConstraintStatus] = []

    for con in result["constraints"]:
        issues = con["issues"]
        con_type = con["type"]

        if not issues:
            statuses.append(
                ConstraintStatus(name=con["name"], type=con_type, fields=con["fields"])
            )
            continue

        kind = issues[0]["kind"]
        detail = issues[0]["detail"]
        fix: Fix | None = None

        if kind == "constraint_missing" and con_type in ("check", "unique"):
            constraint_obj = _find_model_constraint(model, con["name"])
            if constraint_obj:
                fix = AddConstraintFix(table, constraint_obj, model)

        elif kind == "constraint_not_valid" and con_type in ("check", "unique"):
            fix = ValidateConstraintFix(table, con["name"])

        elif kind == "constraint_definition_changed" and con_type == "check":
            constraint_obj = _find_model_constraint(model, con["name"])
            if constraint_obj:
                fix = RebuildConstraintFix(table, constraint_obj, model)

        elif kind == "constraint_extra" and con_type in ("check", "unique"):
            fix = DropConstraintFix(table, con["name"])

        statuses.append(
            ConstraintStatus(
                name=con["name"],
                type=con_type,
                fields=con["fields"],
                issue=detail,
                fix=fix,
            )
        )

    return statuses


# Helpers


def _find_model_index(model: type[Model], name: str) -> Index | None:
    for index in model.model_options.indexes:
        if index.name == name:
            return index
    return None


def _find_model_constraint(model: type[Model], name: str) -> BaseConstraint | None:
    for constraint in model.model_options.constraints:
        if constraint.name == name:
            return constraint
    return None

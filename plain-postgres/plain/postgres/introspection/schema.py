from __future__ import annotations

from typing import Any, TypedDict

from ..db import get_connection


class SchemaIssue(TypedDict):
    kind: str
    name: str
    detail: str


class ColumnInfo(TypedDict):
    name: str
    field_name: str
    type: str
    nullable: bool
    primary_key: bool
    pk_suffix: str
    issues: list[SchemaIssue]


class IndexInfo(TypedDict):
    name: str
    fields: list[str]
    issues: list[SchemaIssue]


class ConstraintInfo(TypedDict):
    name: str
    type: str
    fields: list[str]
    issues: list[SchemaIssue]


class ModelSchemaResult(TypedDict):
    label: str
    table: str
    columns: list[ColumnInfo]
    indexes: list[IndexInfo]
    constraints: list[ConstraintInfo]
    issues: list[SchemaIssue]


def get_actual_columns(cursor: Any, table_name: str) -> dict[str, tuple[str, bool]]:
    """Return {column_name: (type_string, is_not_null)} from the actual DB."""
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
        name: (type_str, is_not_null)
        for name, type_str, is_not_null in cursor.fetchall()
    }


def get_unknown_tables(conn: Any | None = None) -> list[str]:
    """Return sorted list of database tables not managed by any Plain model."""
    from ..migrations.recorder import MIGRATION_TABLE_NAME

    if conn is None:
        conn = get_connection()
    return sorted(
        set(conn.table_names()) - set(conn.plain_table_names()) - {MIGRATION_TABLE_NAME}
    )


def count_issues(result: ModelSchemaResult) -> int:
    """Count all issues across a model result (table-level + item-level)."""
    count = len(result["issues"])
    for col in result["columns"]:
        count += len(col["issues"])
    for idx in result["indexes"]:
        count += len(idx["issues"])
    for con in result["constraints"]:
        count += len(con["issues"])
    return count


def check_model(conn: Any, cursor: Any, model: Any) -> ModelSchemaResult:
    """Compare model against actual database schema. Returns structured result."""
    from ..constraints import CheckConstraint, UniqueConstraint
    from ..fields.related import ForeignKeyField

    table_name = model.model_options.db_table
    columns: list[ColumnInfo] = []
    indexes: list[IndexInfo] = []
    constraints: list[ConstraintInfo] = []

    actual_columns = get_actual_columns(cursor, table_name)

    if not actual_columns:
        return ModelSchemaResult(
            label=model.model_options.label,
            table=table_name,
            columns=columns,
            indexes=indexes,
            constraints=constraints,
            issues=[
                SchemaIssue(
                    kind="table_missing",
                    name=table_name,
                    detail="table missing from database",
                )
            ],
        )

    actual_constraints_raw = conn.get_constraints(cursor, table_name)

    actual_indexes: dict[str, dict[str, Any]] = {}
    actual_unique: dict[str, dict[str, Any]] = {}
    actual_check: dict[str, dict[str, Any]] = {}
    actual_fk: dict[str, dict[str, Any]] = {}
    for name, info in actual_constraints_raw.items():
        if info.get("primary_key"):
            continue
        if info.get("unique"):
            actual_unique[name] = info
        elif info.get("check"):
            actual_check[name] = info
        elif info.get("foreign_key"):
            actual_fk[name] = info
        elif info.get("index"):
            actual_indexes[name] = info

    # Columns
    expected_col_names: set[str] = set()

    for field in model._model_meta.local_fields:
        db_type = field.db_type()
        if db_type is None:
            continue

        expected_col_names.add(field.column)
        col_issues: list[SchemaIssue] = []

        if field.column not in actual_columns:
            col_issues.append(
                SchemaIssue(
                    kind="column_missing",
                    name=field.column,
                    detail="missing from database",
                )
            )
        else:
            actual_type, actual_not_null = actual_columns[field.column]
            if db_type != actual_type:
                col_issues.append(
                    SchemaIssue(
                        kind="type_mismatch",
                        name=field.column,
                        detail=f"expected {db_type}, actual {actual_type}",
                    )
                )
            if (not field.allow_null) != actual_not_null:
                exp = "NOT NULL" if not field.allow_null else "NULL"
                act = "NOT NULL" if actual_not_null else "NULL"
                col_issues.append(
                    SchemaIssue(
                        kind="null_mismatch",
                        name=field.column,
                        detail=f"expected {exp}, actual {act}",
                    )
                )

        pk_suffix = ""
        if field.primary_key:
            pk_suffix = field.db_type_suffix() or ""

        columns.append(
            ColumnInfo(
                name=field.column,
                field_name=field.name,
                type=db_type,
                nullable=field.allow_null,
                primary_key=field.primary_key,
                pk_suffix=pk_suffix,
                issues=col_issues,
            )
        )

    for col_name in sorted(actual_columns.keys() - expected_col_names):
        actual_type, actual_not_null = actual_columns[col_name]
        columns.append(
            ColumnInfo(
                name=col_name,
                field_name="",
                type=actual_type,
                nullable=not actual_not_null,
                primary_key=False,
                pk_suffix="",
                issues=[
                    SchemaIssue(
                        kind="column_extra",
                        name=col_name,
                        detail="extra column, not in model",
                    )
                ],
            )
        )

    # Indexes
    model_indexes = model.model_options.indexes

    for index in model_indexes:
        idx_issues: list[SchemaIssue] = []
        if index.name not in actual_indexes:
            idx_issues.append(
                SchemaIssue(
                    kind="index_missing",
                    name=index.name,
                    detail="missing from database",
                )
            )
        elif not actual_indexes[index.name].get("valid", True):
            idx_issues.append(
                SchemaIssue(
                    kind="index_invalid",
                    name=index.name,
                    detail="INVALID — needs drop and recreate",
                )
            )
        indexes.append(
            IndexInfo(
                name=index.name,
                fields=list(index.fields) if index.fields else [],
                issues=idx_issues,
            )
        )

    for name in sorted(actual_indexes.keys() - {idx.name for idx in model_indexes}):
        cols = actual_indexes[name].get("columns", [])
        indexes.append(
            IndexInfo(
                name=name,
                fields=list(cols) if cols else [],
                issues=[
                    SchemaIssue(kind="index_extra", name=name, detail="not in model")
                ],
            )
        )

    # Unique and check constraints (both matched by name)
    for constraint_cls, constraint_type, actual_dict in [
        (UniqueConstraint, "unique", actual_unique),
        (CheckConstraint, "check", actual_check),
    ]:
        model_constraints = [
            c for c in model.model_options.constraints if isinstance(c, constraint_cls)
        ]
        expected_names = {c.name for c in model_constraints}

        for constraint in model_constraints:
            con_issues: list[SchemaIssue] = []
            if constraint.name not in actual_dict:
                con_issues.append(
                    SchemaIssue(
                        kind="constraint_missing",
                        name=constraint.name,
                        detail="missing from database",
                    )
                )
            elif not actual_dict[constraint.name].get("validated", True):
                con_issues.append(
                    SchemaIssue(
                        kind="constraint_not_valid",
                        name=constraint.name,
                        detail="NOT VALID — needs validation",
                    )
                )
            constraints.append(
                ConstraintInfo(
                    name=constraint.name,
                    type=constraint_type,
                    fields=list(getattr(constraint, "fields", None) or []),
                    issues=con_issues,
                )
            )

        for name in sorted(actual_dict.keys() - expected_names):
            constraints.append(
                ConstraintInfo(
                    name=name,
                    type=constraint_type,
                    fields=list(actual_dict[name].get("columns") or []),
                    issues=[
                        SchemaIssue(
                            kind="constraint_extra",
                            name=name,
                            detail="not in model",
                        )
                    ],
                )
            )

    # Foreign key constraints
    # Match by (column, target_table, target_column) since constraint names are generated.
    expected_fks: dict[tuple[str, str, str], str] = {}
    for field in model._model_meta.local_fields:
        if isinstance(field, ForeignKeyField) and field.db_constraint:
            to_table = field.target_field.model.model_options.db_table
            to_column = field.target_field.column
            expected_fks[(field.column, to_table, to_column)] = field.name

    # Index actual FKs by their shape for O(1) matching
    actual_fk_by_shape: dict[tuple[str, str, str], str] = {}
    for name, info in actual_fk.items():
        fk_target = info.get("foreign_key", ())
        fk_cols = info.get("columns", [])
        if len(fk_cols) == 1 and len(fk_target) == 2:
            actual_fk_by_shape[(fk_cols[0], fk_target[0], fk_target[1])] = name

    matched_fk_names: set[str] = set()
    for key, field_name in expected_fks.items():
        if actual_name := actual_fk_by_shape.get(key):
            matched_fk_names.add(actual_name)
        else:
            col, to_table, to_column = key
            constraints.append(
                ConstraintInfo(
                    name=f"{field_name} → {to_table}.{to_column}",
                    type="fk",
                    fields=[col],
                    issues=[
                        SchemaIssue(
                            kind="constraint_missing",
                            name=col,
                            detail="missing from database",
                        )
                    ],
                )
            )

    for name in sorted(actual_fk.keys() - matched_fk_names):
        info = actual_fk[name]
        fk_target = info.get("foreign_key", ())
        target_str = f"{fk_target[0]}.{fk_target[1]}" if len(fk_target) == 2 else "?"
        constraints.append(
            ConstraintInfo(
                name=name,
                type="fk",
                fields=list(info.get("columns") or []),
                issues=[
                    SchemaIssue(
                        kind="constraint_extra",
                        name=name,
                        detail=f"not in model (→ {target_str})",
                    )
                ],
            )
        )

    return ModelSchemaResult(
        label=model.model_options.label,
        table=table_name,
        columns=columns,
        indexes=indexes,
        constraints=constraints,
        issues=[],
    )

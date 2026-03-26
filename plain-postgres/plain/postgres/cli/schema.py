from __future__ import annotations

import sys
from typing import Any

import click

from ..db import get_connection
from ..registry import models_registry


def _ok() -> None:
    click.secho("  ✓", fg="green", dim=True)


def _err(msg: str) -> None:
    click.secho(f"  ✗ {msg}", fg="red")


def _get_actual_columns(cursor: Any, table_name: str) -> dict[str, tuple[str, bool]]:
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


def _show_model(conn: Any, cursor: Any, model: Any) -> int:
    """Print schema for a model, annotating any drift. Returns issue count."""
    from ..constraints import UniqueConstraint

    table_name = model.model_options.db_table
    issues = 0

    actual_columns = _get_actual_columns(cursor, table_name)
    actual_constraints = conn.get_constraints(cursor, table_name)

    actual_indexes: dict[str, dict[str, Any]] = {}
    actual_unique: dict[str, dict[str, Any]] = {}
    for name, info in actual_constraints.items():
        if info.get("primary_key"):
            continue
        if info.get("index"):
            actual_indexes[name] = info
        elif info.get("unique"):
            actual_unique[name] = info

    click.secho(model.model_options.label, bold=True, nl=False)
    click.secho(f"  →  {table_name}", dim=True)

    if not actual_columns:
        click.echo("  ", nl=False)
        _err("table missing from database")
        return 1

    # Columns
    expected_col_names: set[str] = set()

    for field in model._model_meta.local_fields:
        db_type = field.db_type()
        if db_type is None:
            continue

        expected_col_names.add(field.column)
        expected_type = db_type

        col_display = field.column
        if field.column != field.name:
            col_display = f"{field.name} → {field.column}"

        type_parts = [click.style(db_type, fg="cyan")]
        if field.allow_null:
            type_parts.append(click.style("NULL", dim=True))
        if field.primary_key:
            type_parts.append(click.style("PK", fg="yellow"))
            suffix = field.db_type_suffix()
            if suffix:
                type_parts.append(click.style(suffix, dim=True))

        click.echo(f"  {col_display:30s}  {' '.join(type_parts)}", nl=False)

        if field.column not in actual_columns:
            _err("missing from database")
            issues += 1
        else:
            actual_type, actual_not_null = actual_columns[field.column]
            col_issues = []
            if expected_type != actual_type:
                col_issues.append(
                    f"type: expected {expected_type}, actual {actual_type}"
                )
            if (not field.allow_null) != actual_not_null:
                exp = "NOT NULL" if not field.allow_null else "NULL"
                act = "NOT NULL" if actual_not_null else "NULL"
                col_issues.append(f"expected {exp}, actual {act}")
            if col_issues:
                _err("; ".join(col_issues))
                issues += len(col_issues)
            else:
                _ok()

    for col_name in sorted(actual_columns.keys() - expected_col_names):
        click.echo(f"  {col_name:30s}  ", nl=False)
        _err("extra column, not in model")
        issues += 1

    # Indexes
    model_indexes = model.model_options.indexes
    extra_indexes = actual_indexes.keys() - {idx.name for idx in model_indexes}

    if model_indexes or extra_indexes:
        click.echo()
        click.secho("  Indexes:", dim=True)

    for index in model_indexes:
        fields_str = ", ".join(index.fields) if index.fields else "expressions"
        click.echo(f"    {index.name}  ({fields_str})", nl=False)

        if index.name not in actual_indexes:
            _err("missing from database")
            issues += 1
        else:
            _ok()

    for name in sorted(extra_indexes):
        cols = actual_indexes[name].get("columns", [])
        cols_str = ", ".join(cols) if cols else "expression"
        click.echo(f"    {name}  ({cols_str})", nl=False)
        _err("not in model")
        issues += 1

    # Unique constraints
    model_constraints = [
        c for c in model.model_options.constraints if isinstance(c, UniqueConstraint)
    ]
    extra_constraints = actual_unique.keys() - {c.name for c in model_constraints}

    if model_constraints or extra_constraints:
        click.echo()
        click.secho("  Constraints:", dim=True)

    for constraint in model_constraints:
        if constraint.fields:
            fields_str = ", ".join(constraint.fields)
        else:
            fields_str = "expressions"
        click.echo(f"    {constraint.name}  UNIQUE ({fields_str})", nl=False)

        if constraint.name not in actual_unique:
            _err("missing from database")
            issues += 1
        else:
            _ok()

    for name in sorted(extra_constraints):
        cols = actual_unique[name].get("columns", [])
        cols_str = ", ".join(cols) if cols else "?"
        click.echo(f"    {name}  UNIQUE ({cols_str})", nl=False)
        _err("not in model")
        issues += 1

    return issues


@click.command()
@click.argument("model_label", required=False)
def schema(model_label: str | None) -> None:
    """Show database schema from models, compared against the actual database"""
    models = models_registry.get_models()

    if model_label:
        model_label_lower = model_label.lower()
        models = [
            m
            for m in models
            if m.model_options.label_lower == model_label_lower
            or m.model_options.db_table == model_label
            or m.__name__.lower() == model_label_lower
        ]
        if not models:
            raise click.ClickException(f"No model found matching '{model_label}'")

    conn = get_connection()
    total_issues = 0
    models_checked = 0

    with conn.cursor() as cursor:
        for i, model in enumerate(models):
            if i > 0:
                click.echo()
            models_checked += 1
            total_issues += _show_model(conn, cursor, model)

    click.echo()
    if total_issues == 0:
        click.secho(
            f"{models_checked} models, all match the database.",
            fg="green",
        )
    else:
        click.secho(
            f"{models_checked} models, {total_issues} issue{'s' if total_issues != 1 else ''}.",
            fg="red",
        )
        sys.exit(1)

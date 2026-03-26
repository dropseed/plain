from __future__ import annotations

import json
import sys

import click

from ..db import get_connection
from ..introspection import (
    ModelSchemaResult,
    check_model,
    count_issues,
    get_unknown_tables,
)
from ..registry import models_registry


def _ok() -> None:
    click.secho("  ✓", fg="green", dim=True)


def _err(msg: str) -> None:
    click.secho(f"  ✗ {msg}", fg="red")


def _render_model(result: ModelSchemaResult) -> None:
    """Render a model schema result as human-readable output."""
    click.secho(result["label"], bold=True, nl=False)
    click.secho(f"  →  {result['table']}", dim=True)

    # Table missing — nothing else to show
    if not result["columns"]:
        for issue in result["issues"]:
            click.echo("  ", nl=False)
            _err(issue["detail"])
        return

    # Columns
    for col in result["columns"]:
        col_display = col["name"]
        if col["field_name"] and col["field_name"] != col["name"]:
            col_display = f"{col['field_name']} → {col['name']}"

        type_parts = [click.style(col["type"], fg="cyan")]
        if col["nullable"]:
            type_parts.append(click.style("NULL", dim=True))
        if col["primary_key"]:
            type_parts.append(click.style("PK", fg="yellow"))
            if col["pk_suffix"]:
                type_parts.append(click.style(col["pk_suffix"], dim=True))

        click.echo(f"  {col_display:30s}  {' '.join(type_parts)}", nl=False)

        if col["issues"]:
            _err("; ".join(i["detail"] for i in col["issues"]))
        else:
            _ok()

    # Indexes
    if result["indexes"]:
        click.echo()
        click.secho("  Indexes:", dim=True)

    for idx in result["indexes"]:
        fields_str = ", ".join(idx["fields"]) if idx["fields"] else "expressions"
        click.echo(f"    {idx['name']}  ({fields_str})", nl=False)

        if idx["issues"]:
            _err(idx["issues"][0]["detail"])
        else:
            _ok()

    # Constraints
    if result["constraints"]:
        click.echo()
        click.secho("  Constraints:", dim=True)

    for con in result["constraints"]:
        fields_str = ", ".join(con["fields"]) if con["fields"] else "expressions"
        click.echo(f"    {con['name']}  UNIQUE ({fields_str})", nl=False)

        if con["issues"]:
            _err(con["issues"][0]["detail"])
        else:
            _ok()


@click.command()
@click.argument("model_label", required=False)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def schema(model_label: str | None, output_json: bool) -> None:
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

    # Collect structured results
    results: list[ModelSchemaResult] = []
    with conn.cursor() as cursor:
        for model in models:
            results.append(check_model(conn, cursor, model))

    unknown_tables = get_unknown_tables(conn) if not model_label else []
    total_issues = sum(count_issues(r) for r in results) + len(unknown_tables)

    if output_json:
        output = {
            "models_checked": len(results),
            "total_issues": total_issues,
            "models": results,
            "unknown_tables": unknown_tables,
        }
        click.echo(json.dumps(output, indent=2, default=str))
    else:
        for i, result in enumerate(results):
            if i > 0:
                click.echo()
            _render_model(result)

        if unknown_tables:
            click.echo()
            click.secho("Unknown tables", bold=True)
            for table in unknown_tables:
                click.echo(f"  {table:30s}  ", nl=False)
                _err("not managed by any model")

        click.echo()
        parts = []
        parts.append(f"{len(results)} model{'s' if len(results) != 1 else ''}")
        if unknown_tables:
            parts.append(
                f"{len(unknown_tables)} unknown table{'s' if len(unknown_tables) != 1 else ''}"
            )
        if total_issues == 0:
            click.secho(
                f"{', '.join(parts)}, all match the database.",
                fg="green",
            )
        else:
            click.secho(
                f"{', '.join(parts)}, {total_issues} issue{'s' if total_issues != 1 else ''}.",
                fg="red",
            )
            sys.exit(1)

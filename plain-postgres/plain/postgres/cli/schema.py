import json
import sys

import click

from ..convergence.analysis import ModelAnalysis, analyze_model
from ..convergence.planning import can_auto_correct
from ..db import get_connection
from ..describe import select_models
from ..introspection import MANAGED_CONSTRAINT_TYPES, get_unknown_tables
from .decorators import database_management_command


def _ok() -> None:
    click.secho("  ✓", fg="green", dim=True)


def _err(msg: str) -> None:
    click.secho(f"  ✗ {msg}", fg="red")


def _correctable(msg: str) -> None:
    click.secho(f"  ~ {msg} (auto-correct)", fg="yellow")


def _unmanaged(type_label: str) -> None:
    click.secho(f"  unmanaged ({type_label})", dim=True)


def _render_model(analysis: ModelAnalysis) -> None:
    """Render a model analysis result as human-readable output."""
    click.secho(analysis.label, bold=True, nl=False)
    click.secho(f"  →  {analysis.table}", dim=True)

    # Table missing — nothing else to show
    if not analysis.columns:
        for issue in analysis.table_issues:
            click.echo("  ", nl=False)
            _err(issue)
        return

    # Columns
    for col in analysis.columns:
        col_display = col.name
        if col.field_name and col.field_name != col.name:
            col_display = f"{col.field_name} → {col.name}"

        type_parts = [click.style(col.type, fg="cyan")]
        if col.nullable:
            type_parts.append(click.style("NULL", dim=True))
        if col.primary_key:
            type_parts.append(click.style("PK", fg="yellow"))
            if col.pk_suffix:
                type_parts.append(click.style(col.pk_suffix, dim=True))

        click.echo(f"  {col_display:30s}  {' '.join(type_parts)}", nl=False)

        if col.issue and col.drifts and all(can_auto_correct(d) for d in col.drifts):
            _correctable(col.issue)
        elif col.issue:
            _err(col.issue)
        else:
            _ok()

    # Indexes
    if analysis.indexes:
        click.echo()
        click.secho("  Indexes:", dim=True)

    for idx in analysis.indexes:
        fields_str = ", ".join(idx.fields) if idx.fields else "expressions"
        click.echo(f"    {idx.name}  ({fields_str})", nl=False)

        if idx.access_method:
            _unmanaged(idx.access_method)
        elif idx.issue and idx.drift and can_auto_correct(idx.drift):
            _correctable(idx.issue)
        elif idx.issue:
            _err(idx.issue)
        else:
            _ok()

    # Constraints
    if analysis.constraints:
        click.echo()
        click.secho("  Constraints:", dim=True)

    for con in analysis.constraints:
        con_label = con.constraint_type.label.upper()
        if con.fields:
            click.echo(
                f"    {con.name}  {con_label} ({', '.join(con.fields)})", nl=False
            )
        else:
            click.echo(f"    {con.name}  {con_label}", nl=False)

        if con.constraint_type not in MANAGED_CONSTRAINT_TYPES:
            _unmanaged(con.constraint_type.label)
        elif con.issue and con.drift and can_auto_correct(con.drift):
            _correctable(con.issue)
        elif con.issue:
            _err(con.issue)
        else:
            _ok()


@click.command()
@click.argument("target", required=False)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@database_management_command
def schema(target: str | None, output_json: bool) -> None:
    """Show database schema from models, compared against the actual database.

    TARGET narrows it to one model (by class name, label or table) or one
    package.
    """
    targets = (target,) if target else ()
    try:
        models = select_models(targets, include_packages=True)
    except LookupError as e:
        raise click.ClickException(str(e)) from e

    conn = get_connection()

    # Collect structured results
    analyses: list[ModelAnalysis] = []
    with conn.cursor() as cursor:
        for model in models:
            analyses.append(analyze_model(conn, cursor, model))

    unknown_tables = get_unknown_tables(conn) if not target else []
    total_issues = sum(a.issue_count for a in analyses) + len(unknown_tables)

    if output_json:
        output = {
            "models_checked": len(analyses),
            "total_issues": total_issues,
            "models": [a.to_dict() for a in analyses],
            "unknown_tables": unknown_tables,
        }
        click.echo(json.dumps(output, indent=2, default=str))
    else:
        for i, analysis in enumerate(analyses):
            if i > 0:
                click.echo()
            _render_model(analysis)

        if unknown_tables:
            click.echo()
            click.secho("Unknown tables", bold=True)
            for table in unknown_tables:
                click.echo(f"  {table:30s}  ", nl=False)
                _err("not managed by any model")

        click.echo()
        parts = []
        parts.append(f"{len(analyses)} model{'s' if len(analyses) != 1 else ''}")
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

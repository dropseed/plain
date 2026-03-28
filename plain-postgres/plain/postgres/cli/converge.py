from __future__ import annotations

import click

from ..db import get_connection
from ..dialect import quote_name
from ..introspection import check_model
from ..registry import models_registry


@click.command()
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt.",
)
def converge(yes: bool) -> None:
    """Fix safe schema mismatches between models and the database.

    Detects column type mismatches that can be fixed without data loss
    (e.g. character varying → text) and applies ALTER COLUMN TYPE statements.
    """
    conn = get_connection()
    fixes: list[tuple[str, str, str, str]] = []  # (table, column, actual, expected)

    with conn.cursor() as cursor:
        for model in models_registry.get_models():
            result = check_model(conn, cursor, model)
            table = result["table"]
            for col in result["columns"]:
                for issue in col["issues"]:
                    if issue["kind"] == "type_mismatch":
                        expected = issue["detail"].split("expected ")[1].split(",")[0]
                        actual = issue["detail"].split("actual ")[1]
                        if _is_safe_type_fix(actual, expected):
                            fixes.append((table, col["name"], actual, expected))

    if not fixes:
        click.secho("Schema is converged — nothing to fix.", fg="green")
        return

    click.secho(
        f"{len(fixes)} column{'s' if len(fixes) != 1 else ''} to fix:\n", bold=True
    )
    for table, column, actual, expected in fixes:
        click.echo(f"  {table}.{column}: ", nl=False)
        click.secho(actual, fg="red", nl=False)
        click.echo(" → ", nl=False)
        click.secho(expected, fg="green")

    click.echo()

    if not yes:
        if not click.confirm("Apply these changes?"):
            return

    click.echo()

    with conn.cursor() as cursor:
        for table, column, actual, expected in fixes:
            sql = f"ALTER TABLE {quote_name(table)} ALTER COLUMN {quote_name(column)} TYPE {expected}"
            click.echo(f"  {sql}")
            cursor.execute(sql)

    conn.commit()

    click.echo()
    click.secho(
        f"Fixed {len(fixes)} column{'s' if len(fixes) != 1 else ''}.", fg="green"
    )


def _is_safe_type_fix(actual: str, expected: str) -> bool:
    """Return True if converting actual → expected is safe (no data loss, no rewrite)."""
    # character varying(N) → text is always safe in PostgreSQL.
    # They use the same storage format; the ALTER is metadata-only.
    if actual.startswith("character varying") and expected == "text":
        return True
    return False

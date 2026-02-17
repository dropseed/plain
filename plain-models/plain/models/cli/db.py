from __future__ import annotations

import subprocess
import sys
import time
from collections import defaultdict
from typing import TYPE_CHECKING, cast

import click

from plain.cli import register_cli

from ..backups.cli import cli as backups_cli
from ..db import OperationalError
from ..db import db_connection as _db_connection
from ..migrations.recorder import MIGRATION_TABLE_NAME
from ..postgres.sql import quote_name

if TYPE_CHECKING:
    from ..postgres.wrapper import DatabaseWrapper

# Cast for type checkers; runtime value is _db_connection (DatabaseConnection)
db_connection = cast("DatabaseWrapper", _db_connection)


@register_cli("db")
@click.group()
def cli() -> None:
    """Database operations"""


cli.add_command(backups_cli)


@cli.command()
@click.argument("parameters", nargs=-1)
def shell(parameters: tuple[str, ...]) -> None:
    """Open an interactive database shell"""
    try:
        db_connection.runshell(list(parameters))
    except FileNotFoundError:
        # Note that we're assuming the FileNotFoundError relates to the
        # command missing. It could be raised for some other reason, in
        # which case this error message would be inaccurate. Still, this
        # message catches the common case.
        click.secho(
            f"You appear not to have the {db_connection.executable_name!r} program installed or on your path.",
            fg="red",
            err=True,
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        click.secho(
            '"{}" returned non-zero exit status {}.'.format(
                " ".join(e.cmd),
                e.returncode,
            ),
            fg="red",
            err=True,
        )
        sys.exit(e.returncode)


@cli.command("drop-unknown-tables")
@click.option(
    "--yes",
    is_flag=True,
    help="Skip confirmation prompt (for non-interactive use).",
)
def drop_unknown_tables(yes: bool) -> None:
    """Drop all tables not associated with a Plain model"""
    db_tables = set(db_connection.table_names())
    model_tables = set(db_connection.plain_table_names())
    unknown_tables = sorted(db_tables - model_tables - {MIGRATION_TABLE_NAME})

    if not unknown_tables:
        click.echo("No unknown tables found.")
        return

    unknown_set = set(unknown_tables)
    table_count = len(unknown_tables)
    tables_label = f"{table_count} table{'s' if table_count != 1 else ''}"

    # Find foreign key constraints from kept tables that reference unknown tables
    cascade_warnings: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    with db_connection.cursor() as cursor:
        for table in unknown_tables:
            cursor.execute(
                """
                SELECT conname, conrelid::regclass
                FROM pg_constraint
                WHERE confrelid = %s::regclass AND contype = 'f'
                """,
                [table],
            )
            for constraint_name, referencing_table in cursor.fetchall():
                if str(referencing_table) not in unknown_set:
                    cascade_warnings[table].append(
                        (constraint_name, str(referencing_table))
                    )

    click.secho("Unknown tables:", fg="yellow", bold=True)
    for table in unknown_tables:
        click.echo(f"  - {table}")
        for constraint_name, referencing_table in cascade_warnings[table]:
            click.secho(
                f"    ⚠ CASCADE will drop constraint {constraint_name} on {referencing_table}",
                fg="red",
            )
    click.echo()

    if not yes:
        if not click.confirm(f"Drop {tables_label} (CASCADE)? This cannot be undone."):
            return

    with db_connection.cursor() as cursor:
        for table in unknown_tables:
            click.echo(f"  Dropping {table}...", nl=False)
            cursor.execute(f"DROP TABLE IF EXISTS {quote_name(table)} CASCADE")
            click.echo(" OK")

    click.secho(f"✓ Dropped {tables_label}.", fg="green")


@cli.command()
def wait() -> None:
    """Wait for the database to be ready"""
    attempts = 0
    while True:
        attempts += 1
        waiting_for = False

        try:
            db_connection.ensure_connection()
        except OperationalError:
            waiting_for = True

        if waiting_for:
            if attempts > 1:
                # After the first attempt, start printing them
                click.secho(
                    f"Waiting for database (attempt {attempts})",
                    fg="yellow",
                )
            time.sleep(1.5)
        else:
            click.secho("✔ Database ready", fg="green")
            break

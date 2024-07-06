import subprocess
import sys
import time

import click

from plain.models.db import DEFAULT_DB_ALIAS, OperationalError, connections


@click.group()
def cli():
    pass


@cli.command()
@click.option(
    "--database",
    default=DEFAULT_DB_ALIAS,
    help=(
        "Nominates a database onto which to open a shell. Defaults to the "
        '"default" database.'
    ),
)
@click.argument("parameters", nargs=-1)
def db_shell(database, parameters):
    """Runs the command-line client for specified database, or the default database if none is provided."""
    connection = connections[database]
    try:
        connection.client.runshell(parameters)
    except FileNotFoundError:
        # Note that we're assuming the FileNotFoundError relates to the
        # command missing. It could be raised for some other reason, in
        # which case this error message would be inaccurate. Still, this
        # message catches the common case.
        click.secho(
            "You appear not to have the %r program installed or on your path."
            % connection.client.executable_name,
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


@cli.command()
def db_wait():
    """Wait for the database to be ready"""
    attempts = 0
    while True:
        attempts += 1
        waiting_for = []

        for conn in connections.all():
            try:
                conn.ensure_connection()
            except OperationalError:
                waiting_for.append(conn.alias)

        if waiting_for:
            click.secho(
                f"Waiting for database (attempt {attempts}): {', '.join(waiting_for)}",
                fg="yellow",
            )
            time.sleep(1.5)
        else:
            click.secho(f"Database ready: {', '.join(connections)}", fg="green")
            break

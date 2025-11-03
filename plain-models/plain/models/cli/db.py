from __future__ import annotations

import subprocess
import sys
import time
from typing import TYPE_CHECKING, cast

import click

from plain.cli import register_cli

from ..backups.cli import cli as backups_cli
from ..db import OperationalError
from ..db import db_connection as _db_connection

if TYPE_CHECKING:
    from ..backends.base.base import BaseDatabaseWrapper

    db_connection = cast("BaseDatabaseWrapper", _db_connection)
else:
    db_connection = _db_connection


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
        db_connection.client.runshell(list(parameters))
    except FileNotFoundError:
        # Note that we're assuming the FileNotFoundError relates to the
        # command missing. It could be raised for some other reason, in
        # which case this error message would be inaccurate. Still, this
        # message catches the common case.
        click.secho(
            f"You appear not to have the {db_connection.client.executable_name!r} program installed or on your path.",
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

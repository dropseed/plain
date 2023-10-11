import json
import os
import subprocess
import sys

import click
import requests

from bolt.runtime import settings

from .container import DBContainer


@click.group("db")
def cli():
    """Start, stop, and manage the local Postgres database"""
    pass


@cli.command()
@click.option("--logs", is_flag=True)
def start(logs):
    container = DBContainer()
    container.start()
    if logs:
        container.logs()


@cli.command()
def stop():
    DBContainer().stop()
    click.secho("Database stopped", fg="green")


@cli.command()
def shell():
    DBContainer().shell()


@cli.command()
def reset():
    DBContainer().reset(create=True)
    click.secho("Local development database reset", fg="green")


@cli.group()
def snapshot():
    """Manage local database snapshots"""
    pass


@snapshot.command("create")
@click.argument("name")
@click.pass_context
def snapshot_create(ctx, name):
    """Create a snapshot of the main database"""
    created = DBContainer().create_snapshot(name)
    if not created:
        click.secho(f'Snapshot "{name}" already exists', fg="red")
        sys.exit(1)

    click.secho(f'Snapshot "{name}" created', fg="green")
    print()
    ctx.invoke(snapshot_list)


@snapshot.command("list")
def snapshot_list():
    """List all snapshots"""
    DBContainer().list_snapshots()


@snapshot.command("restore")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True)
def snapshot_restore(name, yes):
    """Restore a snapshot to the main database"""
    if not yes:
        click.confirm(
            f'Are you sure you want to restore snapshot "{name}" to the main database?',
            abort=True,
        )

    DBContainer().restore_snapshot(name)
    click.secho(f'Snapshot "{name}" restored', fg="green")


@snapshot.command("delete")
@click.argument("name")
@click.pass_context
def snapshot_delete(ctx, name):
    """Delete a snapshot"""
    deleted = DBContainer().delete_snapshot(name)
    if not deleted:
        click.secho(f'Snapshot "{name}" does not exist', fg="red")
        sys.exit(1)
    click.secho(f'Snapshot "{name}" deleted', fg="green")
    print()
    ctx.invoke(snapshot_list)


if __name__ == "__main__":
    cli()

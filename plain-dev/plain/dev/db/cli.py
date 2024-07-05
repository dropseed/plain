import os
import sys

import click

from ..services import Services
from .container import DBContainer


@click.group("db")
def cli():
    """Start, stop, and manage the local Postgres database"""
    pass


# @cli.command()
# def reset():
#     DBContainer().reset(create=True)
#     click.secho("Local development database reset", fg="green")


@cli.command()
@click.argument("export_path", default="")
def export(export_path):
    """Export the local database to a file"""
    if not export_path:
        current_dir_name = os.path.basename(os.getcwd())
        export_path = f"{current_dir_name}-dev-db.sql"
    with Services():
        export_successful = DBContainer().export(export_path)

    if export_successful:
        click.secho(f"Local development database exported to {export_path}", fg="green")
    else:
        click.secho("Export failed", fg="red")
        sys.exit(1)


@cli.command("import")
@click.argument("sql_file")
def import_db(sql_file):
    """Import a database file into the local database"""

    print(f"Importing {sql_file} ({os.path.getsize(sql_file) / 1024 / 1024:.2f} MB)")

    with Services():
        successful = DBContainer().import_sql(sql_file)

    if successful:
        click.secho(f"Local development database imported from {sql_file}", fg="green")
    else:
        click.secho("Import failed", fg="red")
        sys.exit(1)


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

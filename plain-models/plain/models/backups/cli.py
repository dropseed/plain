import os
import time
from pathlib import Path

import click

from plain.cli import register_cli

from .core import DatabaseBackups


@register_cli("backups")
@click.group("backups")
def cli():
    """Local database backups"""
    pass


@cli.command("list")
def list_backups():
    backups_handler = DatabaseBackups()
    backups = backups_handler.find_backups()
    if not backups:
        click.secho("No backups found", fg="yellow")
        return

    for backup in backups:
        click.secho(
            f"{backup.name} ({backup.updated_at().strftime('%Y-%m-%d %H:%M:%S')})",
            bold=True,
        )

        for backup_file in backup.iter_files():
            size = os.path.getsize(backup_file)
            click.echo(f"- {backup_file.name} ({size / 1024 / 1024:.2f} MB)")

        click.echo()


@cli.command("create")
@click.option("--pg-dump", default="pg_dump", envvar="PG_DUMP")
@click.argument("backup_name", default="")
def create_backup(backup_name, pg_dump):
    backups_handler = DatabaseBackups()

    if not backup_name:
        backup_name = f"backup_{time.strftime('%Y%m%d_%H%M%S')}"

    try:
        backup_dir = backups_handler.create(
            backup_name,
            pg_dump=pg_dump,
        )
    except Exception as e:
        click.secho(str(e), fg="red")
        exit(1)

    click.secho(f"Backup created in {backup_dir.relative_to(Path.cwd())}", fg="green")


@cli.command("restore")
@click.option("--latest", is_flag=True)
@click.option("--pg-restore", default="pg_restore", envvar="PG_RESTORE")
@click.argument("backup_name", default="")
def restore_backup(backup_name, latest, pg_restore):
    backups_handler = DatabaseBackups()

    if backup_name and latest:
        click.secho("Only one of --latest or backup_name is allowed", fg="red")
        exit(1)

    if not backup_name and not latest:
        click.secho("Backup name or --latest is required", fg="red")
        exit(1)

    if not backup_name and latest:
        backup_name = backups_handler.find_backups()[0].name

    click.secho(f"Restoring backup {backup_name}...", bold=True)

    try:
        backups_handler.restore(
            backup_name,
            pg_restore=pg_restore,
        )
    except Exception as e:
        click.secho(str(e), fg="red")
        exit(1)
    click.echo(f"Backup {backup_name} restored successfully.")


@cli.command("delete")
@click.argument("backup_name")
def delete_backup(backup_name):
    backups_handler = DatabaseBackups()
    try:
        backups_handler.delete(backup_name)
    except Exception as e:
        click.secho(str(e), fg="red")
        return
    click.secho(f"Backup {backup_name} deleted", fg="green")


@cli.command("clear")
@click.confirmation_option(prompt="Are you sure you want to delete all backups?")
def clear_backups():
    backups_handler = DatabaseBackups()
    backups = backups_handler.find_backups()
    for backup in backups:
        backup.delete()
    click.secho("All backups deleted", fg="green")

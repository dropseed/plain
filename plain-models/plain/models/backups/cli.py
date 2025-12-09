from __future__ import annotations

import os
import time
from pathlib import Path

import click

from .core import DatabaseBackups, get_git_branch


@click.group("backups")
def cli() -> None:
    """Local database backups"""
    pass


@cli.command("list")
@click.option(
    "--branch",
    "branch",
    is_flag=False,
    flag_value="__current__",
    default=None,
    help="Filter by branch (defaults to current branch if flag used without value)",
)
def list_backups(branch: str | None) -> None:
    """List database backups"""
    backups_handler = DatabaseBackups()
    backups = backups_handler.find_backups()

    # Resolve branch filter
    if branch == "__current__":
        branch = get_git_branch()

    # Filter by branch if specified
    if branch:
        backups = [b for b in backups if b.metadata.get("git_branch") == branch]

    if not backups:
        if branch:
            click.secho(f"No backups found for branch '{branch}'", fg="yellow")
        else:
            click.secho("No backups found", fg="yellow")
        return

    # Calculate column widths
    name_width = max(len(b.name) for b in backups)
    source_width = max(len(b.metadata.get("source") or "-") for b in backups)

    # Print header
    click.secho(
        f"{'NAME':<{name_width}}  {'SOURCE':<{source_width}}  {'SIZE':<10}  BRANCH",
        dim=True,
    )

    # Print rows
    for backup in backups:
        backup_file = backup.path / "default.backup"
        if backup_file.exists():
            size = os.path.getsize(backup_file)
            size_str = f"{size / 1024 / 1024:.2f} MB"
        else:
            size_str = "-"
        metadata = backup.metadata
        source = metadata.get("source") or "-"
        git_branch = metadata.get("git_branch") or "-"

        click.echo(
            f"{backup.name:<{name_width}}  {source:<{source_width}}  {size_str:<10}  {git_branch}"
        )


@cli.command("create")
@click.option("--pg-dump", default="pg_dump", envvar="PG_DUMP")
@click.argument("backup_name", default="")
def create_backup(backup_name: str, pg_dump: str) -> None:
    """Create a database backup"""
    backups_handler = DatabaseBackups()

    if not backup_name:
        backup_name = time.strftime("%Y%m%d_%H%M%S")

    try:
        backup_dir = backups_handler.create(
            backup_name,
            source="manual",
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
def restore_backup(backup_name: str, latest: bool, pg_restore: str) -> None:
    """Restore a database backup"""
    backups_handler = DatabaseBackups()

    if backup_name and latest:
        raise click.UsageError("Only one of --latest or backup_name is allowed")

    if not backup_name and not latest:
        raise click.UsageError("Backup name or --latest is required")

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
def delete_backup(backup_name: str) -> None:
    """Delete a database backup"""
    backups_handler = DatabaseBackups()
    try:
        backups_handler.delete(backup_name)
    except Exception as e:
        click.secho(str(e), fg="red")
        return
    click.secho(f"Backup {backup_name} deleted", fg="green")


@cli.command("clear")
@click.confirmation_option(prompt="Are you sure you want to delete all backups?")
def clear_backups() -> None:
    """Clear all database backups"""
    backups_handler = DatabaseBackups()
    backups = backups_handler.find_backups()
    for backup in backups:
        backup.delete()
    click.secho("All backups deleted", fg="green")

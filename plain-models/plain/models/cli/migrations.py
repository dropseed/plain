from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING, Any, cast

import click

from plain.cli import register_cli
from plain.cli.runtime import common_command
from plain.packages import packages_registry
from plain.runtime import settings
from plain.utils.text import Truncator

from .. import migrations
from ..backups.core import DatabaseBackups
from ..db import db_connection as _db_connection
from ..migrations.autodetector import MigrationAutodetector
from ..migrations.executor import MigrationExecutor
from ..migrations.loader import AmbiguityError, MigrationLoader
from ..migrations.migration import Migration, SettingsTuple
from ..migrations.optimizer import MigrationOptimizer
from ..migrations.questioner import (
    InteractiveMigrationQuestioner,
    NonInteractiveMigrationQuestioner,
)
from ..migrations.recorder import MigrationRecorder
from ..migrations.state import ModelState, ProjectState
from ..migrations.writer import MigrationWriter
from ..registry import models_registry

if TYPE_CHECKING:
    from ..backends.base.base import BaseDatabaseWrapper
    from ..migrations.operations.base import Operation

    db_connection = cast("BaseDatabaseWrapper", _db_connection)
else:
    db_connection = _db_connection


@register_cli("migrations")
@click.group()
def cli() -> None:
    """Database migration management"""


@common_command
@register_cli("makemigrations", shortcut_for="migrations make")
@cli.command("make")
@click.argument("package_labels", nargs=-1)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Just show what migrations would be made; don't actually write them.",
)
@click.option("--empty", is_flag=True, help="Create an empty migration.")
@click.option(
    "--noinput",
    "--no-input",
    "no_input",
    is_flag=True,
    help="Tells Plain to NOT prompt the user for input of any kind.",
)
@click.option("-n", "--name", help="Use this name for migration file(s).")
@click.option(
    "--check",
    is_flag=True,
    help="Exit with a non-zero status if model changes are missing migrations and don't actually write them.",
)
@click.option(
    "-v",
    "--verbosity",
    type=int,
    default=1,
    help="Verbosity level; 0=minimal output, 1=normal output, 2=verbose output, 3=very verbose output",
)
def make(
    package_labels: tuple[str, ...],
    dry_run: bool,
    empty: bool,
    no_input: bool,
    name: str | None,
    check: bool,
    verbosity: int,
) -> None:
    """Create new database migrations"""

    written_files: list[str] = []
    interactive = not no_input
    migration_name = name
    check_changes = check

    def log(msg: str, level: int = 1) -> None:
        if verbosity >= level:
            click.echo(msg)

    def write_migration_files(
        changes: dict[str, list[Migration]],
        update_previous_migration_paths: dict[str, str] | None = None,
    ) -> None:
        """Take a changes dict and write them out as migration files."""
        directory_created = {}
        for package_label, package_migrations in changes.items():
            log(
                click.style(f"Migrations for '{package_label}':", fg="cyan", bold=True),
                level=1,
            )
            for migration in package_migrations:
                writer = MigrationWriter(migration)
                migration_string = os.path.relpath(writer.path)
                log(f"  {click.style(migration_string, fg='yellow')}\n", level=1)
                for operation in migration.operations:
                    log(f"    - {operation.describe()}", level=1)

                if not dry_run:
                    migrations_directory = os.path.dirname(writer.path)
                    if not directory_created.get(package_label):
                        os.makedirs(migrations_directory, exist_ok=True)
                        init_path = os.path.join(migrations_directory, "__init__.py")
                        if not os.path.isfile(init_path):
                            open(init_path, "w").close()
                        directory_created[package_label] = True

                    migration_string = writer.as_string()
                    with open(writer.path, "w", encoding="utf-8") as fh:
                        fh.write(migration_string)
                        written_files.append(writer.path)

                    if update_previous_migration_paths:
                        prev_path = update_previous_migration_paths[package_label]
                        if writer.needs_manual_porting:
                            log(
                                click.style(
                                    f"Updated migration {migration_string} requires manual porting.\n"
                                    f"Previous migration {os.path.relpath(prev_path)} was kept and "
                                    f"must be deleted after porting functions manually.",
                                    fg="yellow",
                                ),
                                level=1,
                            )
                        else:
                            os.remove(prev_path)
                            log(f"Deleted {os.path.relpath(prev_path)}", level=1)
                elif verbosity >= 3:
                    log(
                        click.style(
                            f"Full migrations file '{writer.filename}':",
                            fg="cyan",
                            bold=True,
                        ),
                        level=3,
                    )
                    log(writer.as_string(), level=3)

    # Validate package labels
    package_labels_set = set(package_labels)
    has_bad_labels = False
    for package_label in package_labels_set:
        try:
            packages_registry.get_package_config(package_label)
        except LookupError as err:
            click.echo(str(err), err=True)
            has_bad_labels = True
    if has_bad_labels:
        sys.exit(2)

    # Load the current graph state
    loader = MigrationLoader(None, ignore_no_migrations=True)

    # Raise an error if any migrations are applied before their dependencies.
    # Only the default db_connection is supported.
    loader.check_consistent_history(db_connection)

    # Check for conflicts
    conflicts = loader.detect_conflicts()
    if package_labels_set:
        conflicts = {
            package_label: conflict
            for package_label, conflict in conflicts.items()
            if package_label in package_labels_set
        }

    if conflicts:
        name_str = "; ".join(
            "{} in {}".format(", ".join(names), package)
            for package, names in conflicts.items()
        )
        raise click.ClickException(
            f"Conflicting migrations detected; multiple leaf nodes in the "
            f"migration graph: ({name_str})."
        )

    # Set up questioner
    if interactive:
        questioner = InteractiveMigrationQuestioner(
            specified_packages=package_labels_set,
            dry_run=dry_run,
        )
    else:
        questioner = NonInteractiveMigrationQuestioner(
            specified_packages=package_labels_set,
            dry_run=dry_run,
            verbosity=verbosity,
        )

    # Set up autodetector
    autodetector = MigrationAutodetector(
        loader.project_state(),
        ProjectState.from_models_registry(models_registry),
        questioner,
    )

    # Handle empty migrations if requested
    if empty:
        if not package_labels_set:
            raise click.ClickException(
                "You must supply at least one package label when using --empty."
            )
        changes = {
            package: [Migration("custom", package)] for package in package_labels_set
        }
        changes = autodetector.arrange_for_graph(
            changes=changes,
            graph=loader.graph,
            migration_name=migration_name,
        )
        write_migration_files(changes)
        return

    # Detect changes
    changes = autodetector.changes(
        graph=loader.graph,
        trim_to_packages=package_labels_set or None,
        convert_packages=package_labels_set or None,
        migration_name=migration_name,
    )

    if not changes:
        log(
            "No changes detected"
            if not package_labels_set
            else f"No changes detected in {'package' if len(package_labels_set) == 1 else 'packages'} "
            f"'{', '.join(package_labels_set)}'",
            level=1,
        )
    else:
        if check_changes:
            sys.exit(1)

        write_migration_files(changes)


@common_command
@register_cli("migrate", shortcut_for="migrations apply")
@cli.command("apply")
@click.argument("package_label", required=False)
@click.argument("migration_name", required=False)
@click.option(
    "--fake", is_flag=True, help="Mark migrations as run without actually running them."
)
@click.option(
    "--plan",
    is_flag=True,
    help="Shows a list of the migration actions that will be performed.",
)
@click.option(
    "--check",
    "check_unapplied",
    is_flag=True,
    help="Exits with a non-zero status if unapplied migrations exist and does not actually apply migrations.",
)
@click.option(
    "--backup/--no-backup",
    "backup",
    is_flag=True,
    default=None,
    help="Explicitly enable/disable pre-migration backups.",
)
@click.option(
    "--no-input",
    "--noinput",
    "no_input",
    is_flag=True,
    help="Tells Plain to NOT prompt the user for input of any kind.",
)
@click.option(
    "--atomic-batch/--no-atomic-batch",
    default=None,
    help="Run migrations in a single transaction (auto-detected by default)",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Suppress migration output (used for test database creation).",
)
def apply(
    package_label: str | None,
    migration_name: str | None,
    fake: bool,
    plan: bool,
    check_unapplied: bool,
    backup: bool | None,
    no_input: bool,
    atomic_batch: bool | None,
    quiet: bool,
) -> None:
    """Apply database migrations"""

    def migration_progress_callback(
        action: str,
        *,
        migration: Migration | None = None,
        fake: bool = False,
        operation: Operation | None = None,
        sql_statements: list[str] | None = None,
    ) -> None:
        if quiet:
            return

        if action == "apply_start":
            click.echo()  # Always add newline between migrations
            if fake:
                click.secho(f"{migration} (faked)", fg="cyan")
            else:
                click.secho(f"{migration}", fg="cyan")
        elif action == "apply_success":
            pass  # Already shown via operations
        elif action == "operation_start":
            if operation is not None:
                click.echo(f"  {operation.describe()}", nl=False)
                click.secho("... ", dim=True, nl=False)
        elif action == "operation_success":
            # Show SQL statements (no OK needed, SQL implies success)
            if sql_statements:
                click.echo()  # newline after "..."
                for sql in sql_statements:
                    click.secho(f"    {sql}", dim=True)
            else:
                # No SQL: just add a newline
                click.echo()

    def describe_operation(operation: Any) -> tuple[str, bool]:
        """Return a string that describes a migration operation for --plan."""
        prefix = ""
        is_error = False
        if hasattr(operation, "code"):
            code = operation.code
            action = (code.__doc__ or "") if code else None
        elif hasattr(operation, "sql"):
            action = operation.sql
        else:
            action = ""
        if action is not None:
            action = str(action).replace("\n", "")
        if action:
            action = " -> " + action
        truncated = Truncator(action)
        return prefix + operation.describe() + truncated.chars(40), is_error

    # Get the database we're operating from
    # Hook for backends needing any database preparation
    db_connection.prepare_database()

    # Work out which packages have migrations and which do not
    executor = MigrationExecutor(db_connection, migration_progress_callback)

    # Raise an error if any migrations are applied before their dependencies.
    executor.loader.check_consistent_history(db_connection)

    # Before anything else, see if there's conflicting packages and drop out
    # hard if there are any
    conflicts = executor.loader.detect_conflicts()
    if conflicts:
        name_str = "; ".join(
            "{} in {}".format(", ".join(names), package)
            for package, names in conflicts.items()
        )
        raise click.ClickException(
            "Conflicting migrations detected; multiple leaf nodes in the "
            f"migration graph: ({name_str})."
        )

    # If they supplied command line arguments, work out what they mean.
    target_package_labels_only = True
    targets: list[tuple[str, str]]
    if package_label:
        try:
            packages_registry.get_package_config(package_label)
        except LookupError as err:
            raise click.ClickException(str(err))

        if package_label not in executor.loader.migrated_packages:
            raise click.ClickException(
                f"Package '{package_label}' does not have migrations."
            )

    if package_label and migration_name:
        try:
            migration = executor.loader.get_migration_by_prefix(
                package_label, migration_name
            )
        except AmbiguityError:
            raise click.ClickException(
                f"More than one migration matches '{migration_name}' in package '{package_label}'. "
                "Please be more specific."
            )
        except KeyError:
            raise click.ClickException(
                f"Cannot find a migration matching '{migration_name}' from package '{package_label}'."
            )
        target: tuple[str, str] = (package_label, migration.name)
        if (
            target not in executor.loader.graph.nodes
            and target in executor.loader.replacements
        ):
            incomplete_migration = executor.loader.replacements[target]
            target = incomplete_migration.replaces[-1]  # type: ignore[assignment]
        targets = [target]
        target_package_labels_only = False
    elif package_label:
        targets = [
            key for key in executor.loader.graph.leaf_nodes() if key[0] == package_label
        ]
    else:
        targets = list(executor.loader.graph.leaf_nodes())

    migration_plan = executor.migration_plan(targets)

    if plan:
        if not quiet:
            click.secho("Planned operations:", fg="cyan")
            if not migration_plan:
                click.echo("  No planned migration operations.")
            else:
                for migration in migration_plan:
                    click.secho(str(migration), fg="cyan")
                    for operation in migration.operations:
                        message, is_error = describe_operation(operation)
                        if is_error:
                            click.secho("    " + message, fg="yellow")
                        else:
                            click.echo("    " + message)
        if check_unapplied:
            sys.exit(1)
        return

    if check_unapplied:
        if migration_plan:
            sys.exit(1)
        return

    # Print some useful info
    if not quiet:
        if target_package_labels_only:
            packages = ", ".join(sorted({a for a, n in targets})) or "(none)"
            click.secho("Packages: ", bold=True, nl=False)
            click.secho(packages, dim=True)
            click.echo()  # Add newline after packages
        else:
            click.secho("Target: ", bold=True, nl=False)
            click.secho(f"{targets[0][1]} from {targets[0][0]}", dim=True)
            click.echo()  # Add newline after target

    pre_migrate_state = executor._create_project_state(with_applied_migrations=True)

    if migration_plan:
        # Determine whether to use atomic batch
        use_atomic_batch = False
        atomic_batch_message = None
        if len(migration_plan) > 1:
            # Check database capabilities
            can_rollback_ddl = db_connection.features.can_rollback_ddl

            # Check if all migrations support atomic
            non_atomic_migrations = [m for m in migration_plan if not m.atomic]

            if atomic_batch is True:
                # User explicitly requested atomic batch
                if not can_rollback_ddl:
                    raise click.UsageError(
                        f"--atomic-batch not supported on {db_connection.vendor}. "
                        "Remove the flag or use a database that supports transactional DDL."
                    )
                if non_atomic_migrations:
                    names = ", ".join(
                        f"{m.package_label}.{m.name}" for m in non_atomic_migrations[:3]
                    )
                    if len(non_atomic_migrations) > 3:
                        names += f", and {len(non_atomic_migrations) - 3} more"
                    raise click.UsageError(
                        f"--atomic-batch requested but these migrations have atomic=False: {names}"
                    )
                use_atomic_batch = True
                atomic_batch_message = (
                    f"Running {len(migration_plan)} migrations in atomic batch"
                )
            elif atomic_batch is False:
                # User explicitly disabled atomic batch
                use_atomic_batch = False
                if len(migration_plan) > 1:
                    atomic_batch_message = (
                        f"Running {len(migration_plan)} migrations separately"
                    )
            else:
                # Auto-detect (atomic_batch is None)
                # SQLite is excluded because it requires foreign key constraints to be
                # disabled before entering a transaction, which conflicts with batch mode
                if (
                    can_rollback_ddl
                    and not non_atomic_migrations
                    and db_connection.vendor != "sqlite"
                ):
                    use_atomic_batch = True
                    atomic_batch_message = (
                        f"Running {len(migration_plan)} migrations in atomic batch"
                    )
                else:
                    use_atomic_batch = False
                    if len(migration_plan) > 1:
                        if not can_rollback_ddl:
                            atomic_batch_message = f"Running {len(migration_plan)} migrations separately ({db_connection.vendor} doesn't support batch)"
                        elif non_atomic_migrations:
                            atomic_batch_message = f"Running {len(migration_plan)} migrations separately (some have atomic=False)"
                        elif db_connection.vendor == "sqlite":
                            atomic_batch_message = f"Running {len(migration_plan)} migrations separately (SQLite doesn't support batch)"
                        else:
                            atomic_batch_message = (
                                f"Running {len(migration_plan)} migrations separately"
                            )

        if backup or (backup is None and settings.DEBUG):
            backup_name = f"migrate_{time.strftime('%Y%m%d_%H%M%S')}"
            if not quiet:
                click.secho("Creating backup: ", bold=True, nl=False)
                click.secho(f"{backup_name}", dim=True, nl=False)
                click.secho("... ", dim=True, nl=False)

            backups_handler = DatabaseBackups()
            backups_handler.create(
                backup_name,
                pg_dump=os.environ.get("PG_DUMP", "pg_dump"),
            )

            if not quiet:
                click.echo(click.style("OK", fg="green"))
                click.echo()  # Add blank line after backup output
        else:
            if not quiet:
                click.echo()  # Add blank line after packages/target info

        if not quiet:
            if atomic_batch_message:
                click.secho(
                    f"Applying migrations ({atomic_batch_message.lower()}):", bold=True
                )
            else:
                click.secho("Applying migrations:", bold=True)
        post_migrate_state = executor.migrate(
            targets,
            plan=migration_plan,
            state=pre_migrate_state.clone(),
            fake=fake,
            atomic_batch=use_atomic_batch,
        )
        # post_migrate signals have access to all models. Ensure that all models
        # are reloaded in case any are delayed.
        post_migrate_state.clear_delayed_models_cache()
        post_migrate_packages = post_migrate_state.models_registry

        # Re-render models of real packages to include relationships now that
        # we've got a final state. This wouldn't be necessary if real packages
        # models were rendered with relationships in the first place.
        with post_migrate_packages.bulk_update():
            model_keys = []
            for model_state in post_migrate_packages.real_models:
                model_key = model_state.package_label, model_state.name_lower
                model_keys.append(model_key)
                post_migrate_packages.unregister_model(*model_key)
        post_migrate_packages.render_multiple(
            [
                ModelState.from_model(models_registry.get_model(*model))
                for model in model_keys
            ]
        )

    else:
        if not quiet:
            click.echo("No migrations to apply.")
            # If there's changes that aren't in migrations yet, tell them
            # how to fix it.
            autodetector = MigrationAutodetector(
                executor.loader.project_state(),
                ProjectState.from_models_registry(models_registry),
            )
            changes = autodetector.changes(graph=executor.loader.graph)
            if changes:
                packages = ", ".join(sorted(changes))
                click.echo(
                    f"Your models have changes that are not yet reflected in migrations ({packages})."
                )
                click.echo(
                    "Run 'plain makemigrations' to create migrations for these changes."
                )


@cli.command("list")
@click.argument("package_labels", nargs=-1)
@click.option(
    "--format",
    type=click.Choice(["list", "plan"]),
    default="list",
    help="Output format.",
)
@click.option(
    "-v",
    "--verbosity",
    type=int,
    default=1,
    help="Verbosity level; 0=minimal output, 1=normal output, 2=verbose output, 3=very verbose output",
)
def list_migrations(
    package_labels: tuple[str, ...], format: str, verbosity: int
) -> None:
    """Show all migrations"""

    def _validate_package_names(package_names: tuple[str, ...]) -> None:
        has_bad_names = False
        for package_name in package_names:
            try:
                packages_registry.get_package_config(package_name)
            except LookupError as err:
                click.echo(str(err), err=True)
                has_bad_names = True
        if has_bad_names:
            sys.exit(2)

    def show_list(db_connection: Any, package_names: tuple[str, ...]) -> None:
        """
        Show a list of all migrations on the system, or only those of
        some named packages.
        """
        # Load migrations from disk/DB
        loader = MigrationLoader(db_connection, ignore_no_migrations=True)
        recorder = MigrationRecorder(db_connection)
        recorded_migrations = recorder.applied_migrations()

        graph = loader.graph
        # If we were passed a list of packages, validate it
        package_names_list: list[str]
        if package_names:
            _validate_package_names(package_names)
            package_names_list = list(package_names)
        # Otherwise, show all packages in alphabetic order
        else:
            package_names_list = sorted(loader.migrated_packages)
        # For each app, print its migrations in order from oldest (roots) to
        # newest (leaves).
        for package_name in package_names_list:
            click.secho(package_name, fg="cyan", bold=True)
            shown = set()
            for node in graph.leaf_nodes(package_name):
                for plan_node in graph.forwards_plan(node):
                    if plan_node not in shown and plan_node[0] == package_name:
                        # Give it a nice title if it's a squashed one
                        title = plan_node[1]
                        if graph.nodes[plan_node].replaces:  # type: ignore[union-attr]
                            title += f" ({len(graph.nodes[plan_node].replaces)} squashed migrations)"  # type: ignore[union-attr]
                        applied_migration = loader.applied_migrations.get(plan_node)  # type: ignore[union-attr]
                        # Mark it as applied/unapplied
                        if applied_migration:
                            if plan_node in recorded_migrations:
                                output = f" [X] {title}"
                            else:
                                title += " Run `plain migrate` to finish recording."
                                output = f" [-] {title}"
                            if verbosity >= 2 and hasattr(applied_migration, "applied"):
                                output += f" (applied at {applied_migration.applied.strftime('%Y-%m-%d %H:%M:%S')})"
                            click.echo(output)
                        else:
                            click.echo(f" [ ] {title}")
                        shown.add(plan_node)
            # If we didn't print anything, then a small message
            if not shown:
                click.secho(" (no migrations)", fg="red")

    def show_plan(db_connection: Any, package_names: tuple[str, ...]) -> None:
        """
        Show all known migrations (or only those of the specified package_names)
        in the order they will be applied.
        """
        # Load migrations from disk/DB
        loader = MigrationLoader(db_connection)
        graph = loader.graph
        if package_names:
            _validate_package_names(package_names)
            targets = [key for key in graph.leaf_nodes() if key[0] in package_names]
        else:
            targets = graph.leaf_nodes()
        plan = []
        seen = set()

        # Generate the plan
        for target in targets:
            for migration in graph.forwards_plan(target):
                if migration not in seen:
                    node = graph.node_map[migration]
                    plan.append(node)
                    seen.add(migration)

        # Output
        def print_deps(node: Any) -> str:
            out = []
            for parent in sorted(node.parents):
                out.append(f"{parent.key[0]}.{parent.key[1]}")
            if out:
                return f" ... ({', '.join(out)})"
            return ""

        for node in plan:
            deps = ""
            if verbosity >= 2:
                deps = print_deps(node)
            if node.key in loader.applied_migrations:  # type: ignore[operator]
                click.echo(f"[X]  {node.key[0]}.{node.key[1]}{deps}")
            else:
                click.echo(f"[ ]  {node.key[0]}.{node.key[1]}{deps}")
        if not plan:
            click.secho("(no migrations)", fg="red")

    # Get the database we're operating from

    if format == "plan":
        show_plan(db_connection, package_labels)
    else:
        show_list(db_connection, package_labels)


@cli.command("prune")
@click.option(
    "--yes",
    is_flag=True,
    help="Skip confirmation prompt (for non-interactive use).",
)
def prune(yes: bool) -> None:
    """Remove stale migration records from the database"""
    # Load migrations from disk and database
    loader = MigrationLoader(db_connection, ignore_no_migrations=True)
    recorder = MigrationRecorder(db_connection)
    recorded_migrations = recorder.applied_migrations()

    # Find all prunable migrations (recorded but not on disk)
    all_prunable = [
        migration
        for migration in recorded_migrations
        if migration not in loader.disk_migrations  # type: ignore[operator]
    ]

    if not all_prunable:
        click.echo("No stale migration records found.")
        return

    # Separate into existing packages vs orphaned packages
    existing_packages = set(loader.migrated_packages)
    prunable_existing: dict[str, list[str]] = {}
    prunable_orphaned: dict[str, list[str]] = {}

    for migration in all_prunable:
        package, name = migration
        if package in existing_packages:
            if package not in prunable_existing:
                prunable_existing[package] = []
            prunable_existing[package].append(name)
        else:
            if package not in prunable_orphaned:
                prunable_orphaned[package] = []
            prunable_orphaned[package].append(name)

    # Display what was found
    if prunable_existing:
        click.secho(
            "Stale migration records (from existing packages):",
            fg="yellow",
            bold=True,
        )
        for package in sorted(prunable_existing.keys()):
            click.secho(f"  {package}:", fg="yellow")
            for name in sorted(prunable_existing[package]):
                click.echo(f"    - {name}")
        click.echo()

    if prunable_orphaned:
        click.secho(
            "Orphaned migration records (from removed packages):",
            fg="red",
            bold=True,
        )
        for package in sorted(prunable_orphaned.keys()):
            click.secho(f"  {package}:", fg="red")
            for name in sorted(prunable_orphaned[package]):
                click.echo(f"    - {name}")
        click.echo()

    total_count = sum(len(migs) for migs in prunable_existing.values()) + sum(
        len(migs) for migs in prunable_orphaned.values()
    )

    if not yes:
        click.echo(
            f"Found {total_count} stale migration record{'s' if total_count != 1 else ''}."
        )
        click.echo()

        # Prompt for confirmation if interactive
        if not click.confirm(
            "Do you want to remove these migrations from the database?"
        ):
            return

    # Actually prune the migrations
    click.secho("Pruning migrations...", bold=True)

    for package, migration_names in prunable_existing.items():
        for name in sorted(migration_names):
            click.echo(f"  Pruning {package}.{name}...", nl=False)
            recorder.record_unapplied(package, name)
            click.echo(" OK")

    for package, migration_names in prunable_orphaned.items():
        for name in sorted(migration_names):
            click.echo(f"  Pruning {package}.{name} (orphaned)...", nl=False)
            recorder.record_unapplied(package, name)
            click.echo(" OK")

    click.secho(
        f"✓ Removed {total_count} stale migration record{'s' if total_count != 1 else ''}.",
        fg="green",
    )


@cli.command("squash")
@click.argument("package_label")
@click.argument("start_migration_name", required=False)
@click.argument("migration_name")
@click.option(
    "--no-optimize",
    is_flag=True,
    help="Do not try to optimize the squashed operations.",
)
@click.option(
    "--noinput",
    "--no-input",
    "no_input",
    is_flag=True,
    help="Tells Plain to NOT prompt the user for input of any kind.",
)
@click.option("--squashed-name", help="Sets the name of the new squashed migration.")
@click.option(
    "-v",
    "--verbosity",
    type=int,
    default=1,
    help="Verbosity level; 0=minimal output, 1=normal output, 2=verbose output, 3=very verbose output",
)
def squash(
    package_label: str,
    start_migration_name: str | None,
    migration_name: str,
    no_optimize: bool,
    no_input: bool,
    squashed_name: str | None,
    verbosity: int,
) -> None:
    """Squash multiple migrations into one"""
    interactive = not no_input

    def find_migration(
        loader: MigrationLoader, package_label: str, name: str
    ) -> Migration:
        try:
            return loader.get_migration_by_prefix(package_label, name)
        except AmbiguityError:
            raise click.ClickException(
                f"More than one migration matches '{name}' in package '{package_label}'. Please be more specific."
            )
        except KeyError:
            raise click.ClickException(
                f"Cannot find a migration matching '{name}' from package '{package_label}'."
            )

    # Validate package_label
    try:
        packages_registry.get_package_config(package_label)
    except LookupError as err:
        raise click.ClickException(str(err))

    # Load the current graph state, check the app and migration they asked for exists
    loader = MigrationLoader(db_connection)
    if package_label not in loader.migrated_packages:
        raise click.ClickException(
            f"Package '{package_label}' does not have migrations (so squashmigrations on it makes no sense)"
        )

    migration = find_migration(loader, package_label, migration_name)

    # Work out the list of predecessor migrations
    migrations_to_squash = [
        loader.get_migration(al, mn)
        for al, mn in loader.graph.forwards_plan(
            (migration.package_label, migration.name)
        )
        if al == migration.package_label
    ]

    if start_migration_name:
        start_migration = find_migration(loader, package_label, start_migration_name)
        start = loader.get_migration(
            start_migration.package_label, start_migration.name
        )
        try:
            start_index = migrations_to_squash.index(start)
            migrations_to_squash = migrations_to_squash[start_index:]
        except ValueError:
            raise click.ClickException(
                f"The migration '{start_migration}' cannot be found. Maybe it comes after "
                f"the migration '{migration}'?\n"
                f"Have a look at:\n"
                f"  plain migrations list {package_label}\n"
                f"to debug this issue."
            )

    # Tell them what we're doing and optionally ask if we should proceed
    if verbosity > 0 or interactive:
        click.secho("Will squash the following migrations:", fg="cyan", bold=True)
        for migration in migrations_to_squash:
            click.echo(f" - {migration.name}")

        if interactive:
            if not click.confirm("Do you wish to proceed?"):
                return

    # Load the operations from all those migrations and concat together,
    # along with collecting external dependencies and detecting double-squashing
    operations = []
    dependencies = set()
    # We need to take all dependencies from the first migration in the list
    # as it may be 0002 depending on 0001
    first_migration = True
    for smigration in migrations_to_squash:
        if smigration.replaces:
            raise click.ClickException(
                "You cannot squash squashed migrations! Please transition it to a "
                "normal migration first"
            )
        operations.extend(smigration.operations)
        for dependency in smigration.dependencies:
            if isinstance(dependency, SettingsTuple):
                dependencies.add(dependency)
            elif dependency[0] != smigration.package_label or first_migration:
                dependencies.add(dependency)
        first_migration = False

    if no_optimize:
        if verbosity > 0:
            click.secho("(Skipping optimization.)", fg="yellow")
        new_operations = operations
    else:
        if verbosity > 0:
            click.secho("Optimizing...", fg="cyan")

        optimizer = MigrationOptimizer()
        new_operations = optimizer.optimize(operations, migration.package_label)

        if verbosity > 0:
            if len(new_operations) == len(operations):
                click.echo("  No optimizations possible.")
            else:
                click.echo(
                    f"  Optimized from {len(operations)} operations to {len(new_operations)} operations."
                )

    # Work out the value of replaces (any squashed ones we're re-squashing)
    # need to feed their replaces into ours
    replaces = []
    for migration in migrations_to_squash:
        if migration.replaces:
            replaces.extend(migration.replaces)
        else:
            replaces.append((migration.package_label, migration.name))

    # Make a new migration with those operations
    subclass = type(
        "Migration",
        (migrations.Migration,),
        {
            "dependencies": dependencies,
            "operations": new_operations,
            "replaces": replaces,
        },
    )
    if start_migration_name:
        if squashed_name:
            # Use the name from --squashed-name
            prefix, _ = start_migration.name.split("_", 1)
            name = f"{prefix}_{squashed_name}"
        else:
            # Generate a name
            name = f"{start_migration.name}_squashed_{migration.name}"
        new_migration = subclass(name, package_label)
    else:
        name = f"0001_{'squashed_' + migration.name if not squashed_name else squashed_name}"
        new_migration = subclass(name, package_label)
        new_migration.initial = True

    # Write out the new migration file
    writer = MigrationWriter(new_migration)
    if os.path.exists(writer.path):
        raise click.ClickException(
            f"Migration {new_migration.name} already exists. Use a different name."
        )
    with open(writer.path, "w", encoding="utf-8") as fh:
        fh.write(writer.as_string())

    if verbosity > 0:
        click.secho(
            f"Created new squashed migration {writer.path}", fg="green", bold=True
        )
        click.echo(
            "  You should commit this migration but leave the old ones in place;\n"
            "  the new migration will be used for new installs. Once you are sure\n"
            "  all instances of the codebase have applied the migrations you squashed,\n"
            "  you can delete them."
        )
        if writer.needs_manual_porting:
            click.secho("Manual porting required", fg="yellow", bold=True)
            click.echo(
                "  Your migrations contained functions that must be manually copied over,\n"
                "  as we could not safely copy their implementation.\n"
                "  See the comment at the top of the squashed migration for details."
            )

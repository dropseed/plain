from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from plain.cli import register_cli
from plain.cli.runtime import common_command
from plain.packages import packages_registry
from plain.utils.text import Truncator

from ..db import get_connection
from ..migrations.autodetector import (
    arrange_for_graph,
    describe_changes,
    detect_model_changes,
)
from ..migrations.exceptions import (
    BadMigrationError,
    MigrationSchemaError,
    StaleMigrationRecordsError,
)
from ..migrations.executor import MigrationExecutor
from ..migrations.loader import AmbiguityError, MigrationLoader
from ..migrations.migration import Migration
from ..migrations.questioner import (
    InteractiveMigrationQuestioner,
    MigrationQuestioner,
)
from ..migrations.recorder import MigrationRecorder
from ..migrations.reset import ResetPlan, plan_reset, validate_reset
from ..migrations.state import ModelState, ProjectState
from ..migrations.writer import MigrationWriter
from ..registry import models_registry
from .decorators import cli_schema_lock, database_management_command

if TYPE_CHECKING:
    from ..connection import DatabaseConnection
    from ..migrations.operations.base import Operation


@register_cli("migrations")
@click.group()
def cli() -> None:
    """Database migration management"""


@common_command
@cli.command("create")
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
@database_management_command
def create(
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

    def collect_sql_for_migration(
        migration: Migration,
        project_state: ProjectState,
    ) -> tuple[list[str], ProjectState]:
        """Apply a migration in collect mode and return the SQL statements."""
        with get_connection().schema_editor(collect_sql=True) as editor:
            new_state = migration.apply(project_state, editor)
            return list(editor.executed_sql), new_state

    def write_migration_files(
        changes: dict[str, list[Migration]],
        update_previous_migration_paths: dict[str, str] | None = None,
    ) -> None:
        """Take a changes dict and write them out as migration files."""
        directory_created = {}
        # Track state for SQL collection in dry-run mode.
        sql_state = loader.project_state() if dry_run else None
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
                else:
                    # dry_run is True — show SQL preview and optionally the full file.
                    assert sql_state is not None
                    sql_statements, sql_state = collect_sql_for_migration(
                        migration, sql_state
                    )
                    if sql_statements:
                        log("", level=1)
                        log(
                            click.style("    SQL:", fg="green", bold=True),
                            level=1,
                        )
                        for sql in sql_statements:
                            log(f"      {sql};", level=1)

                    if verbosity >= 3:
                        log(
                            click.style(
                                f"\n    Full migrations file '{writer.filename}':",
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
    loader.check_consistent_history(get_connection())

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
        questioner = MigrationQuestioner(
            specified_packages=package_labels_set,
            dry_run=dry_run,
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
        changes = arrange_for_graph(
            changes, loader.graph, questioner=questioner, migration_name=migration_name
        )
        write_migration_files(changes)
        return

    # Detect changes
    try:
        changes = detect_model_changes(
            loader,
            package_labels=package_labels_set or None,
            questioner=questioner,
            migration_name=migration_name,
        )
    except MigrationSchemaError as e:
        raise click.ClickException(str(e)) from e

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
            for package_label, package_migrations in changes.items():
                log(
                    click.style(
                        f"Migrations for '{package_label}':", fg="cyan", bold=True
                    ),
                    level=1,
                )
                for migration in package_migrations:
                    for operation in migration.operations:
                        log(f"  - {operation.describe()}", level=1)
            sys.exit(1)

        write_migration_files(changes)

    # Warn about packages that have models but no migrations directory.
    # These are silently skipped by the autodetector, which can be confusing
    # when setting up a new app ("No changes detected").
    unmigrated_with_models = []
    for package_label in sorted(loader.unmigrated_packages):
        module_name, _explicit = MigrationLoader.migrations_module(package_label)
        # Skip packages that explicitly opt out of migrations (module_name is None).
        if module_name is not None and models_registry.all_models.get(package_label):
            unmigrated_with_models.append((package_label, module_name))
    if unmigrated_with_models:
        click.echo()
        click.echo(
            click.style(
                "Warning: The following packages have models but no migrations directory:",
                fg="yellow",
            )
        )
        for package_label, module_name in unmigrated_with_models:
            module_path = module_name.replace(".", "/")
            click.echo(
                f"  - {package_label} (create {module_path}/ to enable migrations)"
            )
        click.echo()
        click.echo(
            "To create initial migrations, add the directory and run "
            + click.style("plain migrations create", bold=True)
            + " again."
        )


@common_command
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
@database_management_command
def apply(
    package_label: str | None,
    migration_name: str | None,
    fake: bool,
    plan: bool,
    check_unapplied: bool,
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
            if fake and migration is not None and migration.supersedes:
                click.secho(f"{migration} (baseline: recorded, not run)", fg="cyan")
            elif fake:
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

    # Work out which packages have migrations and which do not
    executor = MigrationExecutor(get_connection(), migration_progress_callback)

    # Raise an error if any migrations are applied before their dependencies.
    # Faking an explicitly named migration is how that history gets repaired,
    # so the check would only block the repair.
    if not (fake and migration_name):
        executor.loader.check_consistent_history(executor.connection)

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
        targets = [(package_label, migration.name)]
        target_package_labels_only = False
    elif package_label:
        targets = [
            key for key in executor.loader.graph.leaf_nodes() if key[0] == package_label
        ]
    else:
        targets = list(executor.loader.graph.leaf_nodes())

    # A named --fake of the baseline itself is how an operator records it by
    # hand, so that one must get past the boundary refusal that stops all else.
    repair_baseline = (
        (package_label, migration.name)
        if fake and package_label and migration_name and migration.supersedes
        else None
    )
    migration_plan = executor.migration_plan(targets, repair_baseline=repair_baseline)
    if repair_baseline is not None:
        extra = [
            m for m in migration_plan if (m.package_label, m.name) != repair_baseline
        ]
        if extra:
            raise click.ClickException(
                f"Recording {repair_baseline[0]}.{repair_baseline[1]} by hand would also "
                f"fake {', '.join(str(m) for m in extra)}. Apply those first, then repeat."
            )

    if plan:
        if not quiet:
            click.secho("Planned operations:", fg="cyan")
            if not migration_plan:
                click.echo("  No planned migration operations.")
            else:
                for migration in migration_plan:
                    key = (migration.package_label, migration.name)
                    if key in executor.record_only:
                        click.secho(
                            f"{migration} (baseline: recorded, not run)", fg="cyan"
                        )
                        continue
                    click.secho(str(migration), fg="cyan")
                    for operation in migration.operations:
                        message, is_error = describe_operation(operation)
                        if is_error:
                            click.secho("    " + message, fg="yellow")
                        else:
                            click.echo("    " + message)
        if check_unapplied and migration_plan:
            sys.exit(1)
        return

    if check_unapplied:
        if migration_plan:
            sys.exit(1)
        return

    # Print some useful info
    if not quiet:
        if not target_package_labels_only:
            click.secho("Target: ", bold=True, nl=False)
            click.secho(f"{targets[0][1]} from {targets[0][0]}", dim=True)
            click.echo()  # Add newline after target
        elif package_label:
            # Only show package name when explicitly targeting a single package
            click.secho("Package: ", bold=True, nl=False)
            click.secho(package_label, dim=True)
            click.echo()  # Add newline after package

    if migration_plan:
        with cli_schema_lock():
            # Re-plan under the lock — another process may have applied some
            # or all of these migrations while we waited for it.
            executor = MigrationExecutor(get_connection(), migration_progress_callback)
            migration_plan = executor.migration_plan(
                targets, repair_baseline=repair_baseline
            )
            if not migration_plan:
                if not quiet:
                    click.echo(
                        "No migrations to apply (another process already applied them)."
                    )
                return

            # Determine whether to use atomic batch
            use_atomic_batch = False
            atomic_batch_message = None
            if len(migration_plan) > 1:
                # Check if all migrations support atomic
                non_atomic_migrations = [m for m in migration_plan if not m.atomic]

                if atomic_batch is True:
                    # User explicitly requested atomic batch
                    if non_atomic_migrations:
                        names = ", ".join(
                            f"{m.package_label}.{m.name}"
                            for m in non_atomic_migrations[:3]
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
                    # Use atomic batch by default
                    if not non_atomic_migrations:
                        use_atomic_batch = True
                        atomic_batch_message = (
                            f"Running {len(migration_plan)} migrations in atomic batch"
                        )
                    else:
                        use_atomic_batch = False
                        if len(migration_plan) > 1:
                            atomic_batch_message = f"Running {len(migration_plan)} migrations separately (some have atomic=False)"

            if not quiet:
                click.echo()  # Add blank line before applying

            if not quiet:
                if atomic_batch_message:
                    click.secho(
                        f"Applying migrations ({atomic_batch_message.lower()}):",
                        bold=True,
                    )
                else:
                    click.secho("Applying migrations:", bold=True)

            pre_migrate_state = executor._create_project_state(
                with_applied_migrations=True
            )
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
            try:
                changes = detect_model_changes(executor.loader)
            except MigrationSchemaError:
                # A pending change can't be generated (e.g. NOT NULL without
                # default). Surface it through `migrations create` rather than
                # here.
                click.echo(
                    "Your models have schema changes that are not yet reflected in migrations."
                )
                click.echo(
                    "Run 'plain migrations create' to create migrations for these changes."
                )
            else:
                if changes:
                    packages = ", ".join(sorted(changes))
                    click.echo(
                        f"Your models have changes that are not yet reflected in migrations ({packages})."
                    )
                    click.echo(
                        "Run 'plain migrations create' to create migrations for these changes."
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
@database_management_command
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

    def show_list(
        connection: DatabaseConnection, package_names: tuple[str, ...]
    ) -> None:
        """
        Show a list of all migrations on the system, or only those of
        some named packages.
        """
        # Load migrations from disk/DB
        loader = MigrationLoader(connection, ignore_no_migrations=True)

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
        adopt_keys = loader.baseline_status.adopt_keys
        for package_name in package_names_list:
            click.secho(package_name, fg="cyan", bold=True)
            shown = set()
            for node in graph.leaf_nodes(package_name):
                for plan_node in graph.forwards_plan(node):
                    if plan_node not in shown and plan_node[0] == package_name:
                        applied_migration = (
                            loader.applied_migrations.get(plan_node)
                            if loader.applied_migrations
                            else None
                        )
                        marker = "X" if applied_migration else " "
                        output = f" [{marker}] {plan_node[1]}"
                        if plan_node in adopt_keys:
                            output += " (baseline: will be recorded, not run)"
                        if (
                            applied_migration
                            and verbosity >= 2
                            and hasattr(applied_migration, "applied")
                        ):
                            output += f" (applied at {applied_migration.applied.strftime('%Y-%m-%d %H:%M:%S')})"
                        click.echo(output)
                        shown.add(plan_node)
            for refusal in loader.baseline_status.refusals:
                if refusal.package_label == package_name:
                    click.secho(f" ! {refusal}", fg="red")
            # If we didn't print anything, then a small message
            if not shown:
                click.secho(" (no migrations)", fg="red")

    def show_plan(
        connection: DatabaseConnection, package_names: tuple[str, ...]
    ) -> None:
        """
        Show all known migrations (or only those of the specified package_names)
        in the order they will be applied.
        """
        # Load migrations from disk/DB
        loader = MigrationLoader(connection)
        assert loader.applied_migrations is not None
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
            if node.key in loader.applied_migrations:
                click.echo(f"[X]  {node.key[0]}.{node.key[1]}{deps}")
            else:
                click.echo(f"[ ]  {node.key[0]}.{node.key[1]}{deps}")
        if not plan:
            click.secho("(no migrations)", fg="red")

    # Get the database we're operating from

    conn = get_connection()
    if format == "plan":
        show_plan(conn, package_labels)
    else:
        show_list(conn, package_labels)


@cli.command("prune")
@click.argument("package_label", required=False)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt.",
)
@database_management_command
def prune(package_label: str | None, yes: bool) -> None:
    """Remove orphan migration records from the database.

    With a PACKAGE_LABEL, remove every record for that package - the way to
    let its baseline run again when the tables are gone.
    """
    # Load migrations from disk and database
    conn = get_connection()
    loader = MigrationLoader(conn, ignore_no_migrations=True)
    assert loader.disk_migrations is not None
    recorder = MigrationRecorder(conn)
    recorded_migrations = recorder.applied_migrations()

    if package_label:
        try:
            packages_registry.get_package_config(package_label)
        except LookupError as err:
            raise click.ClickException(str(err))
        all_prunable = [m for m in recorded_migrations if m[0] == package_label]
    else:
        all_prunable = loader.orphan_records(recorded_migrations)
        # A refusal that prescribes `prune <package>` is why someone runs this.
        for refusal in loader.baseline_status.refusals:
            if isinstance(refusal, StaleMigrationRecordsError):
                click.secho(f"! {refusal}", fg="red")
        retired = [m for m in recorded_migrations if m in loader.retired_to_baseline]
        if retired and all_prunable:
            click.echo(
                f"Keeping {len(retired)} record{'s' if len(retired) != 1 else ''} retired "
                "by a baseline - they are the rollback path across the reset."
            )

    if not all_prunable:
        click.echo("No orphan migration records found.")
        return

    kind = "migration" if package_label else "orphan migration"

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
            f"Every record for {package_label}:"
            if package_label
            else "Orphan migration records (from existing packages):",
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
            f"Found {total_count} {kind} record{'s' if total_count != 1 else ''}."
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
        f"✓ Removed {total_count} {kind} record{'s' if total_count != 1 else ''}.",
        fg="green",
    )


@cli.command()
@click.argument("package_label")
@click.option(
    "--shipped-in",
    "shipped_in",
    default="",
    help="Version this reset ships in; named in the refusal a database that missed the leaf gets, and required before this package can be reset again.",
)
@click.option(
    "--dry-run", is_flag=True, help="Show the baseline and what would be deleted."
)
@database_management_command
def reset(package_label: str, shipped_in: str, dry_run: bool) -> None:
    """Replace a package's migration history with one baseline"""
    try:
        packages_registry.get_package_config(package_label)
    except LookupError as err:
        raise click.ClickException(str(err))

    loader = MigrationLoader(None, ignore_no_migrations=True)

    try:
        pending = detect_model_changes(loader, package_labels={package_label})
    except MigrationSchemaError as e:
        raise click.ClickException(str(e)) from e
    if pending:
        raise click.ClickException(
            f"`{package_label}` has model changes its migrations don't hold - a "
            "baseline would fold them in and databases that adopt it would never "
            "run them:\n  - "
            + "\n  - ".join(describe_changes(pending))
            + "\nRun `plain migrations create` first."
        )

    try:
        plan = plan_reset(loader, package_label, shipped_in=shipped_in)
        _require_committed(plan)
        validate_reset(loader, plan)
    except BadMigrationError as e:
        raise click.ClickException(str(e)) from e

    writer = MigrationWriter(plan.baseline)
    source = writer.as_string()
    if writer.needs_manual_porting:
        raise click.ClickException(
            "The baseline would reference code defined inside a migration file "
            "that this reset deletes. Move it into the app, then reset again."
        )
    baseline_path = plan.migrations_dir / writer.filename

    if dry_run:
        click.echo(source)

    click.secho(
        f"Resetting `{package_label}`: {len(plan.delete)} migration"
        f"{'s' if len(plan.delete) != 1 else ''} -> {plan.baseline.name}",
        bold=True,
    )
    click.echo(f"  Supersedes {plan.sentinel}")
    for path in plan.delete:
        click.echo(f"  Delete {path.name}")

    if dry_run:
        click.echo("Dry run - nothing written or deleted.")
        return

    click.echo(
        "  Recover from any failure with: "
        f"git checkout -- {plan.migrations_dir} && rm {baseline_path}"
    )
    baseline_path.write_text(source, encoding="utf-8")
    for path in plan.delete:
        path.unlink()
    importlib.invalidate_caches()
    try:
        MigrationLoader(None, ignore_no_migrations=True)
    except Exception as e:
        # Put the history back ourselves; the operator gets the reason only.
        baseline_path.unlink()
        try:
            _git(
                ["checkout", "--", *(path.name for path in plan.delete)],
                cwd=plan.migrations_dir,
            )
        except BadMigrationError as restore_error:
            raise click.ClickException(
                f"The written baseline does not load ({e}), and restoring the "
                f"history failed too: {restore_error}"
            ) from e
        raise click.ClickException(
            f"The written baseline does not load ({e}); the history has been "
            "restored and nothing changed."
        ) from e

    click.echo("")
    click.secho(f"Wrote {os.path.relpath(baseline_path)}", fg="green")
    click.echo(
        "Commit the new file and the deletions together; other packages' "
        "dependencies on the deleted names need no edits."
    )
    if not shipped_in:
        click.echo(
            "`shipped_in` is empty - set it in the baseline when this ships, or the "
            "next reset of this package is refused."
        )
    click.echo(
        f"Every environment must have applied `{package_label}.{plan.sentinel}` "
        "before this ships; a database that hasn't will be refused until it does."
    )


def _git(args: list[str], *, cwd: Path) -> str:
    """Run git in `cwd`, ignoring any repository the environment points at.

    Git sets `GIT_DIR` (and friends) for hooks, so a command run from one
    would otherwise answer about the hook's repository. Raises
    `BadMigrationError` when git fails or is missing.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout
    except OSError as e:
        raise BadMigrationError(
            f"git could not be run ({e}). A reset deletes files; it only runs "
            "where git can bring them back."
        ) from e
    except subprocess.CalledProcessError as e:
        raise BadMigrationError(
            f"git could not read {cwd} ({e.stderr.strip() or e}). A reset deletes "
            "files; it only runs where git can bring them back."
        ) from e


def _require_committed(plan: ResetPlan) -> None:
    """Every file about to go must be tracked and unchanged.

    That makes the leaf a committed migration (not one created a minute ago),
    keeps a venv's site-packages out of reach, and makes recovery from any
    failure one git command.
    """
    tracked = _git(["ls-files", "--", "*.py"], cwd=plan.migrations_dir).split()
    untracked = [path.name for path in plan.delete if path.name not in tracked]
    if untracked:
        raise BadMigrationError(
            f"Not tracked by git in {plan.migrations_dir}: {', '.join(untracked)}. "
            "Commit the history first - the leaf becomes the baseline's sentinel, "
            "and every environment must have applied it."
        )
    modified = _git(
        ["status", "--porcelain", "--untracked-files=no", "--", "*.py"],
        cwd=plan.migrations_dir,
    )
    if modified.strip():
        raise BadMigrationError(
            f"{plan.migrations_dir} has uncommitted changes:\n{modified.rstrip()}\n"
            "Commit them first - the leaf migration becomes the baseline's "
            "sentinel, and every environment must have applied it."
        )

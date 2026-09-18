from __future__ import annotations

import pkgutil
import sys
from importlib import import_module, reload
from typing import TYPE_CHECKING, Any

from plain.packages import packages_registry
from plain.postgres.migrations.graph import MigrationGraph
from plain.postgres.migrations.recorder import MigrationRecorder

from .baselines import BaselineStatus, classify_baselines
from .exceptions import (
    AmbiguityError,
    BadMigrationError,
    InconsistentMigrationHistory,
)

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.migrations.migration import Migration

MIGRATIONS_MODULE_NAME = "migrations"


class MigrationLoader:
    """
    Load migration files from disk and their status from the database.

    Migration files are expected to live in the "migrations" directory of
    an app. Their names are entirely unimportant from a code perspective,
    but will probably follow the 1234_name.py convention.

    On initialization, this class will scan those directories, and open and
    read the Python files, looking for a class called Migration, which should
    inherit from plain.postgres.migrations.Migration. See
    plain.postgres.migrations.migration for what that looks like.
    """

    def __init__(
        self,
        connection: DatabaseConnection | None,
        load: bool = True,
        ignore_no_migrations: bool = False,
    ):
        self.connection = connection
        self.disk_migrations: dict[tuple[str, str], Migration] | None = None
        self.applied_migrations: dict[tuple[str, str], Any] | None = None
        self.ignore_no_migrations = ignore_no_migrations
        self.unmigrated_packages: set[str]
        self.migrated_packages: set[str]
        self.graph: MigrationGraph
        # What the planner should do with each baseline, from the records
        # observed in build_graph(). Empty without a connection.
        self.baseline_status: BaselineStatus = BaselineStatus()
        # One baseline per package, and every retired name it stands for.
        self.baselines: dict[str, Migration] = {}
        self.retired_to_baseline: dict[tuple[str, str], tuple[str, str]] = {}
        if load:
            self.build_graph()

    @classmethod
    def migrations_module(cls, package_label: str) -> tuple[str | None, bool]:
        """
        Return the path to the migrations module for the specified package_label
        and a boolean indicating if the module is specified in
        settings.MIGRATION_MODULE.
        """

        # This package (plain-postgres) has different code under migrations/
        if package_label == "plainpostgres":
            return None, True

        app = packages_registry.get_package_config(package_label)
        return f"{app.name}.{MIGRATIONS_MODULE_NAME}", False

    def load_disk(self) -> None:
        """Load the migrations from all INSTALLED_PACKAGES from disk."""
        self.disk_migrations = {}
        self.unmigrated_packages = set()
        self.migrated_packages = set()
        for package_config in packages_registry.get_package_configs():
            # Get the migrations module directory
            module_name, explicit = self.migrations_module(package_config.package_label)
            if module_name is None:
                self.unmigrated_packages.add(package_config.package_label)
                continue
            was_loaded = module_name in sys.modules
            try:
                module = import_module(module_name)
            except ModuleNotFoundError as e:
                if (explicit and self.ignore_no_migrations) or (
                    not explicit
                    and e.name is not None
                    and MIGRATIONS_MODULE_NAME in e.name.split(".")
                ):
                    self.unmigrated_packages.add(package_config.package_label)
                    continue
                raise
            else:
                # Module is not a package (e.g. migrations.py).
                if not hasattr(module, "__path__"):
                    self.unmigrated_packages.add(package_config.package_label)
                    continue
                # Empty directories are namespaces. Namespace packages have no
                # __file__ and don't use a list for __path__. See
                # https://docs.python.org/3/reference/import.html#namespace-packages
                if getattr(module, "__file__", None) is None and not isinstance(
                    module.__path__, list
                ):
                    self.unmigrated_packages.add(package_config.package_label)
                    continue
                # Force a reload if it's already loaded (tests need this)
                if was_loaded:
                    reload(module)
            self.migrated_packages.add(package_config.package_label)
            migration_names = {
                name
                for _, name, is_pkg in pkgutil.iter_modules(module.__path__)
                if not is_pkg and name[0] not in "_~"
            }
            # Load migrations
            for migration_name in migration_names:
                migration_path = f"{module_name}.{migration_name}"
                try:
                    migration_module = import_module(migration_path)
                except ImportError as e:
                    if "bad magic number" in str(e):
                        raise ImportError(
                            f"Couldn't import {migration_path!r} as it appears to be a stale "
                            ".pyc file."
                        ) from e
                    else:
                        raise
                if not hasattr(migration_module, "Migration"):
                    raise BadMigrationError(
                        f"Migration {migration_name} in app {package_config.package_label} has no Migration class"
                    )
                if getattr(migration_module.Migration, "replaces", None):
                    label = package_config.package_label
                    raise BadMigrationError(
                        f"Migration {label}.{migration_name} declares `replaces`, which Plain no longer supports.\n"
                        "To get the codebase and every database back to ordinary records, in order:\n"
                        f"  1. Delete the `replaces = ...` line from {migration_module.__file__}.\n"
                        "  2. Delete any migration file it replaced that is still on disk (otherwise the package has two leaves),\n"
                        f'     and repoint any `dependencies` entry that names a deleted migration to ("{label}", "{migration_name}").\n'
                        "  3. On each database that already applied every replaced migration (check with `plain migrations list`),\n"
                        f"     record this one without running it: plain migrations apply {label} {migration_name} --fake\n"
                        "     A fresh database runs `plain migrations apply` without --fake. A database that applied only some\n"
                        "     of the replaced migrations must finish them on the previous release first.\n"
                        "  4. On each database: plain migrations prune\n"
                        "Do steps 3 and 4 on staging and production before their next deploy."
                    )
                self.disk_migrations[package_config.package_label, migration_name] = (
                    migration_module.Migration(
                        migration_name,
                        package_config.package_label,
                    )
                )

    def register_baselines(self) -> None:
        """One baseline per package; every name it retired resolves to it."""
        assert self.disk_migrations is not None
        for (label, name), migration in self.disk_migrations.items():
            if not migration.supersedes:
                if migration.retired or migration.shipped_in:
                    raise BadMigrationError(
                        f"Migration {label}.{name} sets `retired`/`shipped_in` but no `supersedes`; "
                        "a baseline names the one migration it supersedes."
                    )
                continue
            if label in self.baselines:
                raise BadMigrationError(
                    f"Package {label} has two baseline migrations "
                    f"({self.baselines[label].name} and {name}); a package can have one."
                )
            retired_names = [*migration.retired, migration.supersedes]
            if name in retired_names:
                raise BadMigrationError(
                    f"Baseline {label}.{name} reuses a retired name. A database that "
                    "recorded the old migration would look like it adopted the "
                    "baseline; name it past the old leaf instead."
                )
            for retired in retired_names:
                if (label, retired) in self.disk_migrations:
                    raise BadMigrationError(
                        f"Baseline {label}.{name} retires {retired}, but that migration "
                        "is still on disk. A baseline stands in for deleted history; "
                        "delete the files it replaces."
                    )
            for dependency in migration.dependencies:
                if dependency == (label, name) or (
                    dependency[0] == label and dependency[1] in retired_names
                ):
                    raise BadMigrationError(
                        f"Baseline {label}.{name} depends on {dependency[1]}, which it "
                        "retires. A baseline is its package's root; it depends on other "
                        "packages only."
                    )
            self.baselines[label] = migration
            for retired in retired_names:
                self.retired_to_baseline[label, retired] = (label, name)

    def get_migration(self, package_label: str, name_prefix: str) -> Migration | None:
        """Return the named migration or raise NodeNotFoundError."""
        return self.graph.nodes[package_label, name_prefix]

    def get_migration_by_prefix(
        self, package_label: str, name_prefix: str
    ) -> Migration:
        """
        Return the migration(s) which match the given app label and name_prefix.
        """
        # Do the search
        assert self.disk_migrations is not None, "load_disk() must be called first"
        results = []
        for migration_package_label, migration_name in self.disk_migrations:
            if migration_package_label == package_label and migration_name.startswith(
                name_prefix
            ):
                results.append((migration_package_label, migration_name))
        if len(results) > 1:
            raise AmbiguityError(
                f"There is more than one migration for '{package_label}' with the prefix '{name_prefix}'"
            )
        elif not results:
            raise KeyError(
                f"There is no migration for '{package_label}' with the prefix "
                f"'{name_prefix}'"
            )
        else:
            return self.disk_migrations[results[0]]

    def check_key(
        self, key: tuple[str, str], current_package: str
    ) -> tuple[str, str] | None:
        if (key[1] != "__first__" and key[1] != "__latest__") or key in self.graph:
            return key
        # Special-case __first__, which means "the first migration" for
        # migrated packages, and is ignored for unmigrated packages. It allows
        # migrations create to declare dependencies on packages before they even have
        # migrations.
        if key[0] == current_package:
            # Ignore __first__ references to the same app (#22325)
            return None
        if key[0] in self.unmigrated_packages:
            # This app isn't migrated, but something depends on it.
            # The models will get auto-added into the state, though
            # so we're fine.
            return None
        if key[0] in self.migrated_packages:
            try:
                if key[1] == "__first__":
                    return self.graph.root_nodes(key[0])[0]
                else:  # "__latest__"
                    return self.graph.leaf_nodes(key[0])[0]
            except IndexError:
                if self.ignore_no_migrations:
                    return None
                else:
                    raise BadMigrationError(
                        f"Dependency on app with no migrations: {key[0]}"
                    )
        raise BadMigrationError(f"Dependency on unknown app: {key[0]}")

    def resolved_dependencies(self, migration: Migration) -> list[tuple[str, str]]:
        """The migration's dependencies as graph edges: a dependency on a
        migration a baseline retired points at the baseline. The migration's
        own `dependencies` are left as written."""
        if not self.retired_to_baseline:
            return list(migration.dependencies)
        return [
            self.retired_to_baseline.get(parent, parent)
            for parent in migration.dependencies
        ]

    def add_internal_dependencies(
        self, key: tuple[str, str], migration: Migration
    ) -> None:
        """
        Internal dependencies need to be added first to ensure `__first__`
        dependencies find the correct root node.
        """
        for parent in self.resolved_dependencies(migration):
            # Ignore __first__ references to the same app.
            if parent[0] == key[0] and parent[1] != "__first__":
                # Migration object is used only for error messages in add_dependency
                self.graph.add_dependency(migration, key, parent, skip_validation=True)

    def add_external_dependencies(
        self, key: tuple[str, str], migration: Migration
    ) -> None:
        for parent in self.resolved_dependencies(migration):
            # Skip internal dependencies
            if key[0] == parent[0]:
                continue
            parent = self.check_key(parent, key[0])
            if parent is not None:
                # Migration object is used only for error messages in add_dependency
                self.graph.add_dependency(migration, key, parent, skip_validation=True)

    def build_graph(self) -> None:
        """
        Build a migration dependency graph using both the disk and database.
        You'll need to rebuild the graph if you apply migrations. This isn't
        usually a problem as generally migration stuff runs in a one-shot process.
        """
        self.load_disk()
        assert self.disk_migrations is not None  # load_disk() ensures this
        self._build_graph_from(self.disk_migrations)

    def _build_graph_from(
        self, disk_migrations: dict[tuple[str, str], Migration]
    ) -> None:
        """Build and check the graph over these migrations."""
        self.disk_migrations = disk_migrations
        self.baselines = {}
        self.retired_to_baseline = {}
        self.register_baselines()
        # Load database data
        if self.connection is None:
            self.applied_migrations = {}
        else:
            recorder = MigrationRecorder(self.connection)
            self.applied_migrations = recorder.applied_migrations()
        # To start, populate the migration graph with nodes for ALL migrations
        # and their dependencies.
        self.graph = MigrationGraph()
        for key, migration in self.disk_migrations.items():
            self.graph.add_node(key, migration)
        for key, migration in self.disk_migrations.items():
            # Internal (same app) dependencies.
            self.add_internal_dependencies(key, migration)
        # Add external dependencies now that the internal ones have been resolved.
        for key, migration in self.disk_migrations.items():
            self.add_external_dependencies(key, migration)
        self.graph.validate_consistency()
        self.graph.ensure_not_cyclic()
        if self.connection is not None and self.baselines:
            self.baseline_status = classify_baselines(
                self, self.applied_migrations, self.connection
            )

    def with_migrations(
        self, disk_migrations: dict[tuple[str, str], Migration]
    ) -> MigrationLoader:
        """A loader over a candidate set of migrations: no database, and this
        loader's knowledge of which packages are migrated."""
        candidate = MigrationLoader(
            None, load=False, ignore_no_migrations=self.ignore_no_migrations
        )
        candidate.migrated_packages = self.migrated_packages
        candidate.unmigrated_packages = self.unmigrated_packages
        candidate._build_graph_from(disk_migrations)
        return candidate

    def check_consistent_history(self, connection: DatabaseConnection) -> None:
        """
        Raise InconsistentMigrationHistory if any applied migrations have
        unapplied dependencies.
        """
        recorder = MigrationRecorder(connection)
        applied = recorder.applied_migrations()
        for migration in applied:
            # If the migration is unknown, skip it.
            if migration not in self.graph.nodes:
                continue
            for parent in self.graph.node_map[migration].parents:
                if parent not in applied:
                    # An unrecorded baseline is the planner's: it classifies every
                    # state a package can be in (adopt, run, or refuse with a
                    # message that says why), so this is not an inconsistency.
                    baseline = self.baselines.get(parent.key[0])
                    if baseline is not None and baseline.name == parent.key[1]:
                        continue
                    raise InconsistentMigrationHistory(
                        f"Migration {migration[0]}.{migration[1]} is applied before its dependency "
                        f"{parent[0]}.{parent[1]} on the database."
                    )

    def orphan_records(
        self, applied: dict[tuple[str, str], Any]
    ) -> list[tuple[str, str]]:
        """Recorded migrations with no file on disk that no baseline retired.

        The one definition every reader of "stale record" shares: prune,
        preflight, and plain-dev's branch-switch check. Retired records are
        deliberately excluded - they are what rollback across a reset needs.
        """
        assert self.disk_migrations is not None
        return [
            key
            for key in applied
            if key not in self.disk_migrations and key not in self.retired_to_baseline
        ]

    def detect_conflicts(self) -> dict[str, list[str]]:
        """
        Look through the loaded graph and detect any conflicts - packages
        with more than one leaf migration. Return a dict of the app labels
        that conflict with the migration names that conflict.
        """
        seen_packages = {}
        conflicting_packages = set()
        for package_label, migration_name in self.graph.leaf_nodes():
            if package_label in seen_packages:
                conflicting_packages.add(package_label)
            seen_packages.setdefault(package_label, set()).add(migration_name)
        return {
            package_label: sorted(seen_packages[package_label])
            for package_label in conflicting_packages
        }

    def project_state(
        self, nodes: tuple[str, str] | None = None, at_end: bool = True
    ) -> Any:
        """
        Return a ProjectState object representing the most recent state
        that the loaded migrations represent.

        See graph.make_state() for the meaning of "nodes" and "at_end".
        """
        return self.graph.make_state(
            nodes=nodes, at_end=at_end, real_packages=self.unmigrated_packages
        )

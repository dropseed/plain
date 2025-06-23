import pkgutil
import sys
from importlib import import_module, reload

from plain.models.migrations.graph import MigrationGraph
from plain.models.migrations.recorder import MigrationRecorder
from plain.packages import packages_registry

from .exceptions import (
    AmbiguityError,
    BadMigrationError,
    InconsistentMigrationHistory,
    NodeNotFoundError,
)

MIGRATIONS_MODULE_NAME = "migrations"


class MigrationLoader:
    """
    Load migration files from disk and their status from the database.

    Migration files are expected to live in the "migrations" directory of
    an app. Their names are entirely unimportant from a code perspective,
    but will probably follow the 1234_name.py convention.

    On initialization, this class will scan those directories, and open and
    read the Python files, looking for a class called Migration, which should
    inherit from plain.models.migrations.Migration. See
    plain.models.migrations.migration for what that looks like.

    Some migrations will be marked as "replacing" another set of migrations.
    These are loaded into a separate set of migrations away from the main ones.
    If all the migrations they replace are either unapplied or missing from
    disk, then they are injected into the main set, replacing the named migrations.
    Any dependency pointers to the replaced migrations are re-pointed to the
    new migration.

    This does mean that this class MUST also talk to the database as well as
    to disk, but this is probably fine. We're already not just operating
    in memory.
    """

    def __init__(
        self,
        connection,
        load=True,
        ignore_no_migrations=False,
        replace_migrations=True,
    ):
        self.connection = connection
        self.disk_migrations = None
        self.applied_migrations = None
        self.ignore_no_migrations = ignore_no_migrations
        self.replace_migrations = replace_migrations
        if load:
            self.build_graph()

    @classmethod
    def migrations_module(cls, package_label):
        """
        Return the path to the migrations module for the specified package_label
        and a boolean indicating if the module is specified in
        settings.MIGRATION_MODULE.
        """

        # This package (plain-models) has different code under migrations/
        if package_label == "models":
            return None, True

        app = packages_registry.get_package_config(package_label)
        return f"{app.name}.{MIGRATIONS_MODULE_NAME}", False

    def load_disk(self):
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
                    not explicit and MIGRATIONS_MODULE_NAME in e.name.split(".")
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
                self.disk_migrations[package_config.package_label, migration_name] = (
                    migration_module.Migration(
                        migration_name,
                        package_config.package_label,
                    )
                )

    def get_migration(self, package_label, name_prefix):
        """Return the named migration or raise NodeNotFoundError."""
        return self.graph.nodes[package_label, name_prefix]

    def get_migration_by_prefix(self, package_label, name_prefix):
        """
        Return the migration(s) which match the given app label and name_prefix.
        """
        # Do the search
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

    def check_key(self, key, current_package):
        if (key[1] != "__first__" and key[1] != "__latest__") or key in self.graph:
            return key
        # Special-case __first__, which means "the first migration" for
        # migrated packages, and is ignored for unmigrated packages. It allows
        # makemigrations to declare dependencies on packages before they even have
        # migrations.
        if key[0] == current_package:
            # Ignore __first__ references to the same app (#22325)
            return
        if key[0] in self.unmigrated_packages:
            # This app isn't migrated, but something depends on it.
            # The models will get auto-added into the state, though
            # so we're fine.
            return
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
                    raise ValueError(f"Dependency on app with no migrations: {key[0]}")
        raise ValueError(f"Dependency on unknown app: {key[0]}")

    def add_internal_dependencies(self, key, migration):
        """
        Internal dependencies need to be added first to ensure `__first__`
        dependencies find the correct root node.
        """
        for parent in migration.dependencies:
            # Ignore __first__ references to the same app.
            if parent[0] == key[0] and parent[1] != "__first__":
                self.graph.add_dependency(migration, key, parent, skip_validation=True)

    def add_external_dependencies(self, key, migration):
        for parent in migration.dependencies:
            # Skip internal dependencies
            if key[0] == parent[0]:
                continue
            parent = self.check_key(parent, key[0])
            if parent is not None:
                self.graph.add_dependency(migration, key, parent, skip_validation=True)

    def build_graph(self):
        """
        Build a migration dependency graph using both the disk and database.
        You'll need to rebuild the graph if you apply migrations. This isn't
        usually a problem as generally migration stuff runs in a one-shot process.
        """
        # Load disk data
        self.load_disk()
        # Load database data
        if self.connection is None:
            self.applied_migrations = {}
        else:
            recorder = MigrationRecorder(self.connection)
            self.applied_migrations = recorder.applied_migrations()
        # To start, populate the migration graph with nodes for ALL migrations
        # and their dependencies. Also make note of replacing migrations at this step.
        self.graph = MigrationGraph()
        self.replacements = {}
        for key, migration in self.disk_migrations.items():
            self.graph.add_node(key, migration)
            # Replacing migrations.
            if migration.replaces:
                self.replacements[key] = migration
        for key, migration in self.disk_migrations.items():
            # Internal (same app) dependencies.
            self.add_internal_dependencies(key, migration)
        # Add external dependencies now that the internal ones have been resolved.
        for key, migration in self.disk_migrations.items():
            self.add_external_dependencies(key, migration)
        # Carry out replacements where possible and if enabled.
        if self.replace_migrations:
            for key, migration in self.replacements.items():
                # Get applied status of each of this migration's replacement
                # targets.
                applied_statuses = [
                    (target in self.applied_migrations) for target in migration.replaces
                ]
                # The replacing migration is only marked as applied if all of
                # its replacement targets are.
                if all(applied_statuses):
                    self.applied_migrations[key] = migration
                else:
                    self.applied_migrations.pop(key, None)
                # A replacing migration can be used if either all or none of
                # its replacement targets have been applied.
                if all(applied_statuses) or (not any(applied_statuses)):
                    self.graph.remove_replaced_nodes(key, migration.replaces)
                else:
                    # This replacing migration cannot be used because it is
                    # partially applied. Remove it from the graph and remap
                    # dependencies to it (#25945).
                    self.graph.remove_replacement_node(key, migration.replaces)
        # Ensure the graph is consistent.
        try:
            self.graph.validate_consistency()
        except NodeNotFoundError as exc:
            # Check if the missing node could have been replaced by any squash
            # migration but wasn't because the squash migration was partially
            # applied before. In that case raise a more understandable exception
            # (#23556).
            # Get reverse replacements.
            reverse_replacements = {}
            for key, migration in self.replacements.items():
                for replaced in migration.replaces:
                    reverse_replacements.setdefault(replaced, set()).add(key)
            # Try to reraise exception with more detail.
            if exc.node in reverse_replacements:
                candidates = reverse_replacements.get(exc.node, set())
                is_replaced = any(
                    candidate in self.graph.nodes for candidate in candidates
                )
                if not is_replaced:
                    tries = ", ".join("{}.{}".format(*c) for c in candidates)
                    raise NodeNotFoundError(
                        f"Migration {exc.origin} depends on nonexistent node ('{exc.node[0]}', '{exc.node[1]}'). "
                        f"Plain tried to replace migration {exc.node[0]}.{exc.node[1]} with any of [{tries}] "
                        "but wasn't able to because some of the replaced migrations "
                        "are already applied.",
                        exc.node,
                    ) from exc
            raise
        self.graph.ensure_not_cyclic()

    def check_consistent_history(self, connection):
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
                    # Skip unapplied squashed migrations that have all of their
                    # `replaces` applied.
                    if parent in self.replacements:
                        if all(
                            m in applied for m in self.replacements[parent].replaces
                        ):
                            continue
                    raise InconsistentMigrationHistory(
                        f"Migration {migration[0]}.{migration[1]} is applied before its dependency "
                        f"{parent[0]}.{parent[1]} on the database."
                    )

    def detect_conflicts(self):
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

    def project_state(self, nodes=None, at_end=True):
        """
        Return a ProjectState object representing the most recent state
        that the loaded migrations represent.

        See graph.make_state() for the meaning of "nodes" and "at_end".
        """
        return self.graph.make_state(
            nodes=nodes, at_end=at_end, real_packages=self.unmigrated_packages
        )

    def collect_sql(self, plan):
        """
        Take a migration plan and return a list of collected SQL statements
        that represent the best-efforts version of that plan.
        """
        statements = []
        state = None
        for migration in plan:
            with self.connection.schema_editor(
                collect_sql=True, atomic=migration.atomic
            ) as schema_editor:
                if state is None:
                    state = self.project_state(
                        (migration.package_label, migration.name), at_end=False
                    )

                state = migration.apply(state, schema_editor, collect_sql=True)
            statements.extend(schema_editor.collected_sql)
        return statements

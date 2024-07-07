import os
import sys
import warnings
from itertools import takewhile

from plain.internal.legacy.management.base import (
    BaseCommand,
    CommandError,
    no_translations,
)
from plain.internal.legacy.management.utils import run_formatters
from plain.models.db import DEFAULT_DB_ALIAS, OperationalError, connections, router
from plain.models.migrations import Migration
from plain.models.migrations.autodetector import MigrationAutodetector
from plain.models.migrations.loader import MigrationLoader
from plain.models.migrations.migration import SwappableTuple
from plain.models.migrations.optimizer import MigrationOptimizer
from plain.models.migrations.questioner import (
    InteractiveMigrationQuestioner,
    MigrationQuestioner,
    NonInteractiveMigrationQuestioner,
)
from plain.models.migrations.state import ProjectState
from plain.models.migrations.utils import get_migration_name_timestamp
from plain.models.migrations.writer import MigrationWriter
from plain.packages import packages
from plain.runtime import settings


class Command(BaseCommand):
    help = "Creates new migration(s) for packages."

    def add_arguments(self, parser):
        parser.add_argument(
            "args",
            metavar="package_label",
            nargs="*",
            help="Specify the app label(s) to create migrations for.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Just show what migrations would be made; don't actually write them.",
        )
        parser.add_argument(
            "--merge",
            action="store_true",
            help="Enable fixing of migration conflicts.",
        )
        parser.add_argument(
            "--empty",
            action="store_true",
            help="Create an empty migration.",
        )
        parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_false",
            dest="interactive",
            help="Tells Plain to NOT prompt the user for input of any kind.",
        )
        parser.add_argument(
            "-n",
            "--name",
            help="Use this name for migration file(s).",
        )
        parser.add_argument(
            "--no-header",
            action="store_false",
            dest="include_header",
            help="Do not add header comments to new migration file(s).",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            dest="check_changes",
            help=(
                "Exit with a non-zero status if model changes are missing migrations "
                "and don't actually write them."
            ),
        )
        parser.add_argument(
            "--scriptable",
            action="store_true",
            dest="scriptable",
            help=(
                "Divert log output and input prompts to stderr, writing only "
                "paths of generated migration files to stdout."
            ),
        )
        parser.add_argument(
            "--update",
            action="store_true",
            dest="update",
            help=(
                "Merge model changes into the latest migration and optimize the "
                "resulting operations."
            ),
        )

    @property
    def log_output(self):
        return self.stderr if self.scriptable else self.stdout

    def log(self, msg):
        self.log_output.write(msg)

    @no_translations
    def handle(self, *package_labels, **options):
        self.written_files = []
        self.verbosity = options["verbosity"]
        self.interactive = options["interactive"]
        self.dry_run = options["dry_run"]
        self.merge = options["merge"]
        self.empty = options["empty"]
        self.migration_name = options["name"]
        if self.migration_name and not self.migration_name.isidentifier():
            raise CommandError("The migration name must be a valid Python identifier.")
        self.include_header = options["include_header"]
        check_changes = options["check_changes"]
        self.scriptable = options["scriptable"]
        self.update = options["update"]
        # If logs and prompts are diverted to stderr, remove the ERROR style.
        if self.scriptable:
            self.stderr.style_func = None

        # Make sure the app they asked for exists
        package_labels = set(package_labels)
        has_bad_labels = False
        for package_label in package_labels:
            try:
                packages.get_package_config(package_label)
            except LookupError as err:
                self.stderr.write(str(err))
                has_bad_labels = True
        if has_bad_labels:
            sys.exit(2)

        # Load the current graph state. Pass in None for the connection so
        # the loader doesn't try to resolve replaced migrations from DB.
        loader = MigrationLoader(None, ignore_no_migrations=True)

        # Raise an error if any migrations are applied before their dependencies.
        consistency_check_labels = {
            config.label for config in packages.get_package_configs()
        }
        # Non-default databases are only checked if database routers used.
        aliases_to_check = (
            connections if settings.DATABASE_ROUTERS else [DEFAULT_DB_ALIAS]
        )
        for alias in sorted(aliases_to_check):
            connection = connections[alias]
            if connection.settings_dict[
                "ENGINE"
            ] != "plain.models.backends.dummy" and any(
                # At least one model must be migrated to the database.
                router.allow_migrate(
                    connection.alias, package_label, model_name=model._meta.object_name
                )
                for package_label in consistency_check_labels
                for model in packages.get_package_config(package_label).get_models()
            ):
                try:
                    loader.check_consistent_history(connection)
                except OperationalError as error:
                    warnings.warn(
                        "Got an error checking a consistent migration history "
                        f"performed for database connection '{alias}': {error}",
                        RuntimeWarning,
                    )
        # Before anything else, see if there's conflicting packages and drop out
        # hard if there are any and they don't want to merge
        conflicts = loader.detect_conflicts()

        # If package_labels is specified, filter out conflicting migrations for
        # unspecified packages.
        if package_labels:
            conflicts = {
                package_label: conflict
                for package_label, conflict in conflicts.items()
                if package_label in package_labels
            }

        if conflicts and not self.merge:
            name_str = "; ".join(
                "{} in {}".format(", ".join(names), app)
                for app, names in conflicts.items()
            )
            raise CommandError(
                "Conflicting migrations detected; multiple leaf nodes in the "
                "migration graph: (%s).\nTo fix them run "
                "'python manage.py makemigrations --merge'" % name_str
            )

        # If they want to merge and there's nothing to merge, then politely exit
        if self.merge and not conflicts:
            self.log("No conflicts detected to merge.")
            return

        # If they want to merge and there is something to merge, then
        # divert into the merge code
        if self.merge and conflicts:
            return self.handle_merge(loader, conflicts)

        if self.interactive:
            questioner = InteractiveMigrationQuestioner(
                specified_packages=package_labels,
                dry_run=self.dry_run,
                prompt_output=self.log_output,
            )
        else:
            questioner = NonInteractiveMigrationQuestioner(
                specified_packages=package_labels,
                dry_run=self.dry_run,
                verbosity=self.verbosity,
                log=self.log,
            )
        # Set up autodetector
        autodetector = MigrationAutodetector(
            loader.project_state(),
            ProjectState.from_packages(packages),
            questioner,
        )

        # If they want to make an empty migration, make one for each app
        if self.empty:
            if not package_labels:
                raise CommandError(
                    "You must supply at least one app label when using --empty."
                )
            # Make a fake changes() result we can pass to arrange_for_graph
            changes = {app: [Migration("custom", app)] for app in package_labels}
            changes = autodetector.arrange_for_graph(
                changes=changes,
                graph=loader.graph,
                migration_name=self.migration_name,
            )
            self.write_migration_files(changes)
            return

        # Detect changes
        changes = autodetector.changes(
            graph=loader.graph,
            trim_to_packages=package_labels or None,
            convert_packages=package_labels or None,
            migration_name=self.migration_name,
        )

        if not changes:
            # No changes? Tell them.
            if self.verbosity >= 1:
                if package_labels:
                    if len(package_labels) == 1:
                        self.log(
                            "No changes detected in app '%s'" % package_labels.pop()
                        )
                    else:
                        self.log(
                            "No changes detected in packages '%s'"
                            % ("', '".join(package_labels))
                        )
                else:
                    self.log("No changes detected")
        else:
            if check_changes:
                sys.exit(1)
            if self.update:
                self.write_to_last_migration_files(changes)
            else:
                self.write_migration_files(changes)

    def write_to_last_migration_files(self, changes):
        loader = MigrationLoader(connections[DEFAULT_DB_ALIAS])
        new_changes = {}
        update_previous_migration_paths = {}
        for package_label, app_migrations in changes.items():
            # Find last migration.
            leaf_migration_nodes = loader.graph.leaf_nodes(app=package_label)
            if len(leaf_migration_nodes) == 0:
                raise CommandError(
                    f"Package {package_label} has no migration, cannot update last migration."
                )
            leaf_migration_node = leaf_migration_nodes[0]
            # Multiple leaf nodes have already been checked earlier in command.
            leaf_migration = loader.graph.nodes[leaf_migration_node]
            # Updated migration cannot be a squash migration, a dependency of
            # another migration, and cannot be already applied.
            if leaf_migration.replaces:
                raise CommandError(
                    f"Cannot update squash migration '{leaf_migration}'."
                )
            if leaf_migration_node in loader.applied_migrations:
                raise CommandError(
                    f"Cannot update applied migration '{leaf_migration}'."
                )
            depending_migrations = [
                migration
                for migration in loader.disk_migrations.values()
                if leaf_migration_node in migration.dependencies
            ]
            if depending_migrations:
                formatted_migrations = ", ".join(
                    [f"'{migration}'" for migration in depending_migrations]
                )
                raise CommandError(
                    f"Cannot update migration '{leaf_migration}' that migrations "
                    f"{formatted_migrations} depend on."
                )
            # Build new migration.
            for migration in app_migrations:
                leaf_migration.operations.extend(migration.operations)

                for dependency in migration.dependencies:
                    if isinstance(dependency, SwappableTuple):
                        if settings.AUTH_USER_MODEL == dependency.setting:
                            leaf_migration.dependencies.append(
                                ("__setting__", "AUTH_USER_MODEL")
                            )
                        else:
                            leaf_migration.dependencies.append(dependency)
                    elif dependency[0] != migration.package_label:
                        leaf_migration.dependencies.append(dependency)
            # Optimize migration.
            optimizer = MigrationOptimizer()
            leaf_migration.operations = optimizer.optimize(
                leaf_migration.operations, package_label
            )
            # Update name.
            previous_migration_path = MigrationWriter(leaf_migration).path
            suggested_name = (
                leaf_migration.name[:4] + "_" + leaf_migration.suggest_name()
            )
            if leaf_migration.name == suggested_name:
                new_name = leaf_migration.name + "_updated"
            else:
                new_name = suggested_name
            leaf_migration.name = new_name
            # Register overridden migration.
            new_changes[package_label] = [leaf_migration]
            update_previous_migration_paths[package_label] = previous_migration_path

        self.write_migration_files(new_changes, update_previous_migration_paths)

    def write_migration_files(self, changes, update_previous_migration_paths=None):
        """
        Take a changes dict and write them out as migration files.
        """
        directory_created = {}
        for package_label, app_migrations in changes.items():
            if self.verbosity >= 1:
                self.log(
                    self.style.MIGRATE_HEADING("Migrations for '%s':" % package_label)
                )
            for migration in app_migrations:
                # Describe the migration
                writer = MigrationWriter(migration, self.include_header)
                if self.verbosity >= 1:
                    # Display a relative path if it's below the current working
                    # directory, or an absolute path otherwise.
                    migration_string = self.get_relative_path(writer.path)
                    self.log("  %s\n" % self.style.MIGRATE_LABEL(migration_string))
                    for operation in migration.operations:
                        self.log("    - %s" % operation.describe())
                    if self.scriptable:
                        self.stdout.write(migration_string)
                if not self.dry_run:
                    # Write the migrations file to the disk.
                    migrations_directory = os.path.dirname(writer.path)
                    if not directory_created.get(package_label):
                        os.makedirs(migrations_directory, exist_ok=True)
                        init_path = os.path.join(migrations_directory, "__init__.py")
                        if not os.path.isfile(init_path):
                            open(init_path, "w").close()
                        # We just do this once per app
                        directory_created[package_label] = True
                    migration_string = writer.as_string()
                    with open(writer.path, "w", encoding="utf-8") as fh:
                        fh.write(migration_string)
                        self.written_files.append(writer.path)
                    if update_previous_migration_paths:
                        prev_path = update_previous_migration_paths[package_label]
                        rel_prev_path = self.get_relative_path(prev_path)
                        if writer.needs_manual_porting:
                            migration_path = self.get_relative_path(writer.path)
                            self.log(
                                self.style.WARNING(
                                    f"Updated migration {migration_path} requires "
                                    f"manual porting.\n"
                                    f"Previous migration {rel_prev_path} was kept and "
                                    f"must be deleted after porting functions manually."
                                )
                            )
                        else:
                            os.remove(prev_path)
                            self.log(f"Deleted {rel_prev_path}")
                elif self.verbosity == 3:
                    # Alternatively, makemigrations --dry-run --verbosity 3
                    # will log the migrations rather than saving the file to
                    # the disk.
                    self.log(
                        self.style.MIGRATE_HEADING(
                            "Full migrations file '%s':" % writer.filename
                        )
                    )
                    self.log(writer.as_string())
        run_formatters(self.written_files)

    @staticmethod
    def get_relative_path(path):
        try:
            migration_string = os.path.relpath(path)
        except ValueError:
            migration_string = path
        if migration_string.startswith(".."):
            migration_string = path
        return migration_string

    def handle_merge(self, loader, conflicts):
        """
        Handles merging together conflicted migrations interactively,
        if it's safe; otherwise, advises on how to fix it.
        """
        if self.interactive:
            questioner = InteractiveMigrationQuestioner(prompt_output=self.log_output)
        else:
            questioner = MigrationQuestioner(defaults={"ask_merge": True})

        for package_label, migration_names in conflicts.items():
            # Grab out the migrations in question, and work out their
            # common ancestor.
            merge_migrations = []
            for migration_name in migration_names:
                migration = loader.get_migration(package_label, migration_name)
                migration.ancestry = [
                    mig
                    for mig in loader.graph.forwards_plan(
                        (package_label, migration_name)
                    )
                    if mig[0] == migration.package_label
                ]
                merge_migrations.append(migration)

            def all_items_equal(seq):
                return all(item == seq[0] for item in seq[1:])

            merge_migrations_generations = zip(*(m.ancestry for m in merge_migrations))
            common_ancestor_count = sum(
                1
                for common_ancestor_generation in takewhile(
                    all_items_equal, merge_migrations_generations
                )
            )
            if not common_ancestor_count:
                raise ValueError(
                    "Could not find common ancestor of %s" % migration_names
                )
            # Now work out the operations along each divergent branch
            for migration in merge_migrations:
                migration.branch = migration.ancestry[common_ancestor_count:]
                migrations_ops = (
                    loader.get_migration(node_app, node_name).operations
                    for node_app, node_name in migration.branch
                )
                migration.merged_operations = sum(migrations_ops, [])
            # In future, this could use some of the Optimizer code
            # (can_optimize_through) to automatically see if they're
            # mergeable. For now, we always just prompt the user.
            if self.verbosity > 0:
                self.log(self.style.MIGRATE_HEADING("Merging %s" % package_label))
                for migration in merge_migrations:
                    self.log(self.style.MIGRATE_LABEL("  Branch %s" % migration.name))
                    for operation in migration.merged_operations:
                        self.log("    - %s" % operation.describe())
            if questioner.ask_merge(package_label):
                # If they still want to merge it, then write out an empty
                # file depending on the migrations needing merging.
                numbers = [
                    MigrationAutodetector.parse_number(migration.name)
                    for migration in merge_migrations
                ]
                try:
                    biggest_number = max(x for x in numbers if x is not None)
                except ValueError:
                    biggest_number = 1
                subclass = type(
                    "Migration",
                    (Migration,),
                    {
                        "dependencies": [
                            (package_label, migration.name)
                            for migration in merge_migrations
                        ],
                    },
                )
                parts = ["%04i" % (biggest_number + 1)]
                if self.migration_name:
                    parts.append(self.migration_name)
                else:
                    parts.append("merge")
                    leaf_names = "_".join(
                        sorted(migration.name for migration in merge_migrations)
                    )
                    if len(leaf_names) > 47:
                        parts.append(get_migration_name_timestamp())
                    else:
                        parts.append(leaf_names)
                migration_name = "_".join(parts)
                new_migration = subclass(migration_name, package_label)
                writer = MigrationWriter(new_migration, self.include_header)

                if not self.dry_run:
                    # Write the merge migrations file to the disk
                    with open(writer.path, "w", encoding="utf-8") as fh:
                        fh.write(writer.as_string())
                    run_formatters([writer.path])
                    if self.verbosity > 0:
                        self.log("\nCreated new merge migration %s" % writer.path)
                        if self.scriptable:
                            self.stdout.write(writer.path)
                elif self.verbosity == 3:
                    # Alternatively, makemigrations --merge --dry-run --verbosity 3
                    # will log the merge migrations rather than saving the file
                    # to the disk.
                    self.log(
                        self.style.MIGRATE_HEADING(
                            "Full merge migrations file '%s':" % writer.filename
                        )
                    )
                    self.log(writer.as_string())

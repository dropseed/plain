import sys

from plain.internal.legacy.management.base import BaseCommand
from plain.models.db import DEFAULT_DB_ALIAS, connections
from plain.models.migrations.loader import MigrationLoader
from plain.models.migrations.recorder import MigrationRecorder
from plain.packages import packages


class Command(BaseCommand):
    help = "Shows all available migrations for the current project"

    def add_arguments(self, parser):
        parser.add_argument(
            "package_label",
            nargs="*",
            help="Package labels of applications to limit the output to.",
        )
        parser.add_argument(
            "--database",
            default=DEFAULT_DB_ALIAS,
            help=(
                "Nominates a database to show migrations for. Defaults to the "
                '"default" database.'
            ),
        )

        formats = parser.add_mutually_exclusive_group()
        formats.add_argument(
            "--list",
            "-l",
            action="store_const",
            dest="format",
            const="list",
            help=(
                "Shows a list of all migrations and which are applied. "
                "With a verbosity level of 2 or above, the applied datetimes "
                "will be included."
            ),
        )
        formats.add_argument(
            "--plan",
            "-p",
            action="store_const",
            dest="format",
            const="plan",
            help=(
                "Shows all migrations in the order they will be applied. With a "
                "verbosity level of 2 or above all direct migration dependencies and "
                "reverse dependencies (run_before) will be included."
            ),
        )

        parser.set_defaults(format="list")

    def handle(self, *args, **options):
        self.verbosity = options["verbosity"]

        # Get the database we're operating from
        db = options["database"]
        connection = connections[db]

        if options["format"] == "plan":
            return self.show_plan(connection, options["package_label"])
        else:
            return self.show_list(connection, options["package_label"])

    def _validate_package_names(self, loader, package_names):
        has_bad_names = False
        for package_name in package_names:
            try:
                packages.get_package_config(package_name)
            except LookupError as err:
                self.stderr.write(str(err))
                has_bad_names = True
        if has_bad_names:
            sys.exit(2)

    def show_list(self, connection, package_names=None):
        """
        Show a list of all migrations on the system, or only those of
        some named packages.
        """
        # Load migrations from disk/DB
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        recorder = MigrationRecorder(connection)
        recorded_migrations = recorder.applied_migrations()
        graph = loader.graph
        # If we were passed a list of packages, validate it
        if package_names:
            self._validate_package_names(loader, package_names)
        # Otherwise, show all packages in alphabetic order
        else:
            package_names = sorted(loader.migrated_packages)
        # For each app, print its migrations in order from oldest (roots) to
        # newest (leaves).
        for package_name in package_names:
            self.stdout.write(package_name, self.style.MIGRATE_LABEL)
            shown = set()
            for node in graph.leaf_nodes(package_name):
                for plan_node in graph.forwards_plan(node):
                    if plan_node not in shown and plan_node[0] == package_name:
                        # Give it a nice title if it's a squashed one
                        title = plan_node[1]
                        if graph.nodes[plan_node].replaces:
                            title += " (%s squashed migrations)" % len(
                                graph.nodes[plan_node].replaces
                            )
                        applied_migration = loader.applied_migrations.get(plan_node)
                        # Mark it as applied/unapplied
                        if applied_migration:
                            if plan_node in recorded_migrations:
                                output = " [X] %s" % title
                            else:
                                title += " Run 'manage.py migrate' to finish recording."
                                output = " [-] %s" % title
                            if self.verbosity >= 2 and hasattr(
                                applied_migration, "applied"
                            ):
                                output += (
                                    " (applied at %s)"
                                    % applied_migration.applied.strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    )
                                )
                            self.stdout.write(output)
                        else:
                            self.stdout.write(" [ ] %s" % title)
                        shown.add(plan_node)
            # If we didn't print anything, then a small message
            if not shown:
                self.stdout.write(" (no migrations)", self.style.ERROR)

    def show_plan(self, connection, package_names=None):
        """
        Show all known migrations (or only those of the specified package_names)
        in the order they will be applied.
        """
        # Load migrations from disk/DB
        loader = MigrationLoader(connection)
        graph = loader.graph
        if package_names:
            self._validate_package_names(loader, package_names)
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
        def print_deps(node):
            out = []
            for parent in sorted(node.parents):
                out.append("{}.{}".format(*parent.key))
            if out:
                return " ... (%s)" % ", ".join(out)
            return ""

        for node in plan:
            deps = ""
            if self.verbosity >= 2:
                deps = print_deps(node)
            if node.key in loader.applied_migrations:
                self.stdout.write(f"[X]  {node.key[0]}.{node.key[1]}{deps}")
            else:
                self.stdout.write(f"[ ]  {node.key[0]}.{node.key[1]}{deps}")
        if not plan:
            self.stdout.write("(no migrations)", self.style.ERROR)

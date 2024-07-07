import shutil
import sys

from plain.internal.legacy.management.base import BaseCommand, CommandError
from plain.internal.legacy.management.utils import run_formatters
from plain.models import migrations
from plain.models.migrations.exceptions import AmbiguityError
from plain.models.migrations.loader import MigrationLoader
from plain.models.migrations.optimizer import MigrationOptimizer
from plain.models.migrations.writer import MigrationWriter
from plain.packages import packages
from plain.runtime import __version__


class Command(BaseCommand):
    help = "Optimizes the operations for the named migration."

    def add_arguments(self, parser):
        parser.add_argument(
            "package_label",
            help="Package label of the application to optimize the migration for.",
        )
        parser.add_argument(
            "migration_name", help="Migration name to optimize the operations for."
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit with a non-zero status if the migration can be optimized.",
        )

    def handle(self, *args, **options):
        verbosity = options["verbosity"]
        package_label = options["package_label"]
        migration_name = options["migration_name"]
        check = options["check"]

        # Validate package_label.
        try:
            packages.get_package_config(package_label)
        except LookupError as err:
            raise CommandError(str(err))

        # Load the current graph state.
        loader = MigrationLoader(None)
        if package_label not in loader.migrated_packages:
            raise CommandError(f"Package '{package_label}' does not have migrations.")
        # Find a migration.
        try:
            migration = loader.get_migration_by_prefix(package_label, migration_name)
        except AmbiguityError:
            raise CommandError(
                f"More than one migration matches '{migration_name}' in app "
                f"'{package_label}'. Please be more specific."
            )
        except KeyError:
            raise CommandError(
                f"Cannot find a migration matching '{migration_name}' from app "
                f"'{package_label}'."
            )

        # Optimize the migration.
        optimizer = MigrationOptimizer()
        new_operations = optimizer.optimize(
            migration.operations, migration.package_label
        )
        if len(migration.operations) == len(new_operations):
            if verbosity > 0:
                self.stdout.write("No optimizations possible.")
            return
        else:
            if verbosity > 0:
                self.stdout.write(
                    "Optimizing from %d operations to %d operations."
                    % (len(migration.operations), len(new_operations))
                )
            if check:
                sys.exit(1)

        # Set the new migration optimizations.
        migration.operations = new_operations

        # Write out the optimized migration file.
        writer = MigrationWriter(migration)
        migration_file_string = writer.as_string()
        if writer.needs_manual_porting:
            if migration.replaces:
                raise CommandError(
                    "Migration will require manual porting but is already a squashed "
                    "migration.\nTransition to a normal migration first: "
                    "https://docs.djangoproject.com/en/%s/topics/migrations/"
                    "#squashing-migrations" % __version__
                )
            # Make a new migration with those operations.
            subclass = type(
                "Migration",
                (migrations.Migration,),
                {
                    "dependencies": migration.dependencies,
                    "operations": new_operations,
                    "replaces": [(migration.package_label, migration.name)],
                },
            )
            optimized_migration_name = "%s_optimized" % migration.name
            optimized_migration = subclass(optimized_migration_name, package_label)
            writer = MigrationWriter(optimized_migration)
            migration_file_string = writer.as_string()
            if verbosity > 0:
                self.stdout.write(
                    self.style.MIGRATE_HEADING("Manual porting required") + "\n"
                    "  Your migrations contained functions that must be manually "
                    "copied over,\n"
                    "  as we could not safely copy their implementation.\n"
                    "  See the comment at the top of the optimized migration for "
                    "details."
                )
                if shutil.which("black"):
                    self.stdout.write(
                        self.style.WARNING(
                            "Optimized migration couldn't be formatted using the "
                            '"black" command. You can call it manually.'
                        )
                    )
        with open(writer.path, "w", encoding="utf-8") as fh:
            fh.write(migration_file_string)
        run_formatters([writer.path])

        if verbosity > 0:
            self.stdout.write(
                self.style.MIGRATE_HEADING(f"Optimized migration {writer.path}")
            )

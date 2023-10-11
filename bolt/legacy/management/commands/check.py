from bolt import preflight
from bolt.legacy.management.base import BaseCommand
from bolt.packages import packages


class Command(BaseCommand):
    help = "Checks the entire Bolt project for potential problems."

    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("args", metavar="package_label", nargs="*")
        parser.add_argument(
            "--deploy",
            action="store_true",
            help="Check deployment settings.",
        )
        parser.add_argument(
            "--fail-level",
            default="ERROR",
            choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
            help=(
                "Message level that will cause the command to exit with a "
                "non-zero status. Default is ERROR."
            ),
        )
        parser.add_argument(
            "--database",
            action="append",
            dest="databases",
            help="Run database related checks against these aliases.",
        )

    def handle(self, *package_labels, **options):
        include_deployment_checks = options["deploy"]

        if package_labels:
            package_configs = [
                packages.get_package_config(package_label)
                for package_label in package_labels
            ]
        else:
            package_configs = None

        self.check(
            package_configs=package_configs,
            display_num_errors=True,
            include_deployment_checks=include_deployment_checks,
            fail_level=getattr(preflight, options["fail_level"]),
            databases=options["databases"],
        )

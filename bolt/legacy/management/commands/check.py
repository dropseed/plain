from bolt import preflight
from bolt.legacy.management.base import BaseCommand, CommandError
from bolt.packages import packages
from bolt.preflight.registry import registry


class Command(BaseCommand):
    help = "Checks the entire Bolt project for potential problems."

    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("args", metavar="package_label", nargs="*")
        parser.add_argument(
            "--tag",
            "-t",
            action="append",
            dest="tags",
            help="Run only checks labeled with given tag.",
        )
        parser.add_argument(
            "--list-tags",
            action="store_true",
            help="List available tags.",
        )
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
        if options["list_tags"]:
            self.stdout.write(
                "\n".join(sorted(registry.tags_available(include_deployment_checks)))
            )
            return

        if package_labels:
            package_configs = [
                packages.get_package_config(package_label)
                for package_label in package_labels
            ]
        else:
            package_configs = None

        tags = options["tags"]
        if tags:
            try:
                invalid_tag = next(
                    tag
                    for tag in tags
                    if not preflight.tag_exists(tag, include_deployment_checks)
                )
            except StopIteration:
                # no invalid tags
                pass
            else:
                raise CommandError(
                    'There is no system check with the "%s" tag.' % invalid_tag
                )

        self.check(
            package_configs=package_configs,
            tags=tags,
            display_num_errors=True,
            include_deployment_checks=include_deployment_checks,
            fail_level=getattr(preflight, options["fail_level"]),
            databases=options["databases"],
        )

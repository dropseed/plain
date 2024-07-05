import importlib
from importlib.metadata import entry_points
from importlib.util import find_spec

import click

from bolt.packages import packages


class InstalledPackagesGroup(click.Group):
    """
    Packages in INSTALLED_PACKAGES with a cli.py module
    will be discovered automatically.
    """

    BOLT_APPS_PREFIX = "bolt."
    MODULE_NAME = "cli"

    def list_commands(self, ctx):
        packages_with_commands = []

        # Get installed packages with a cli.py module
        for app in packages.get_package_configs():
            if not find_spec(f"{app.name}.{self.MODULE_NAME}"):
                continue

            cli_name = app.name

            if cli_name.startswith(self.BOLT_APPS_PREFIX):
                cli_name = cli_name[len(self.BOLT_APPS_PREFIX) :]

            packages_with_commands.append(cli_name)

        return packages_with_commands

    def get_command(self, ctx, name):
        # Try it as bolt.x and just x (we don't know ahead of time which it is, but prefer bolt.x)
        for n in [self.BOLT_APPS_PREFIX + name, name]:
            try:
                cli = importlib.import_module(f"{n}.{self.MODULE_NAME}")
            except ModuleNotFoundError:
                continue

            # Get the app's cli.py group
            try:
                return cli.cli
            except AttributeError:
                continue


class EntryPointGroup(click.Group):
    """
    Python packages can be added to the Plain CLI
    via the bolt_cli entrypoint in their setup.py.

    This is intended for packages that don't go in INSTALLED_PACKAGES.
    """

    ENTRYPOINT_NAME = "bolt.cli"

    def list_commands(self, ctx):
        rv = []

        for entry_point in entry_points().select(group=self.ENTRYPOINT_NAME):
            rv.append(entry_point.name)

        rv.sort()
        return rv

    def get_command(self, ctx, name):
        for entry_point in entry_points().select(group=self.ENTRYPOINT_NAME):
            if entry_point.name == name:
                return entry_point.load()

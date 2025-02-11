import importlib
from importlib.metadata import entry_points
from importlib.util import find_spec

import click

from plain.packages import packages


class InstalledPackagesGroup(click.Group):
    """
    Packages in INSTALLED_PACKAGES with a cli.py module
    will be discovered automatically.
    """

    PLAIN_APPS_PREFIX = "plain."
    APP_PREFIX = "app."
    MODULE_NAME = "cli"

    def list_commands(self, ctx):
        command_names = []

        # Get installed packages with a cli.py module
        for app in packages.get_package_configs():
            if not find_spec(f"{app.name}.{self.MODULE_NAME}"):
                continue

            cli_name = app.name

            # Change plain.{pkg} to just {pkg}
            if cli_name.startswith(self.PLAIN_APPS_PREFIX):
                cli_name = cli_name[len(self.PLAIN_APPS_PREFIX) :]

            # Change app.{pkg} to just {pkg}
            if cli_name.startswith(self.APP_PREFIX):
                cli_name = cli_name[len(self.APP_PREFIX) :]

            if cli_name in command_names:
                raise ValueError(
                    f"Duplicate command name {cli_name} found in installed packages."
                )

            command_names.append(cli_name)

        return command_names

    def get_command(self, ctx, name):
        # Try it as plain.x, app.x, and just x (we don't know ahead of time which it is)
        for n in [self.PLAIN_APPS_PREFIX + name, self.APP_PREFIX + name, name]:
            try:
                if not find_spec(n):
                    # plain.<name> doesn't exist at all
                    continue
            except ModuleNotFoundError:
                continue

            try:
                if not find_spec(f"{n}.{self.MODULE_NAME}"):
                    continue
            except ModuleNotFoundError:
                continue

            cli = importlib.import_module(f"{n}.{self.MODULE_NAME}")

            # Get the app's cli.py group
            try:
                return cli.cli
            except AttributeError:
                continue


class EntryPointGroup(click.Group):
    """
    Python packages can be added to the Plain CLI
    via the plain_cli entrypoint in their setup.py.

    This is intended for packages that don't go in INSTALLED_PACKAGES.
    """

    ENTRYPOINT_NAME = "plain.cli"

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

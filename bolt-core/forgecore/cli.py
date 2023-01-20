import importlib
import os
import subprocess
import sys

import click

from .core import Forge


class NamespaceGroup(click.Group):
    COMMAND_PREFIX = "forge-"

    def list_commands(self, ctx):
        bin_dir = os.path.dirname(sys.executable)
        rv = []
        for filename in os.listdir(bin_dir):
            if filename.startswith(self.COMMAND_PREFIX):
                rv.append(filename[len(self.COMMAND_PREFIX) :])

        rv.sort()
        return rv

    def get_command(self, ctx, name):
        # Remove hyphens and prepend w/ "forge"
        # so "pre-commit" becomes "forgeprecommit" as an import
        import_name = "forge" + name.replace("-", "")
        try:
            i = importlib.import_module(import_name)
            return i.cli
        except ImportError:
            # Built-in commands will appear here,
            # but so would failed imports of new ones
            pass
        except AttributeError as e:
            click.secho(f'Error importing "{import_name}":\n  {e}\n', fg="red")


@click.group()
def cli():
    pass


@cli.command
def docs():
    """Open the Forge documentation in your browser"""
    subprocess.run(["open", "https://www.forgepackages.com/docs/?ref=cli"])


@cli.command(
    context_settings=dict(
        ignore_unknown_options=True,
    )
)
@click.argument("managepy_args", nargs=-1, type=click.UNPROCESSED)
def django(managepy_args):
    """Pass commands to Django manage.py"""
    result = Forge().manage_cmd(*managepy_args)
    if result.returncode:
        sys.exit(result.returncode)


@cli.command(
    context_settings=dict(
        ignore_unknown_options=True,
    )
)
@click.argument("makemigrations_args", nargs=-1, type=click.UNPROCESSED)
def makemigrations(makemigrations_args):
    """Alias to Django `makemigrations`"""
    result = Forge().manage_cmd("makemigrations", *makemigrations_args)
    if result.returncode:
        sys.exit(result.returncode)


@cli.command(
    context_settings=dict(
        ignore_unknown_options=True,
    )
)
@click.argument("migrate_args", nargs=-1, type=click.UNPROCESSED)
def migrate(migrate_args):
    """Alias to Django `migrate`"""
    result = Forge().manage_cmd("migrate", *migrate_args)
    if result.returncode:
        sys.exit(result.returncode)


@cli.command()
def shell():
    """Alias to Django `shell`"""
    Forge().manage_cmd("shell")


cli = click.CommandCollection(sources=[NamespaceGroup(), cli])


if __name__ == "__main__":
    cli()

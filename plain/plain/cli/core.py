import traceback

import click
from click.core import Command, Context

import plain.runtime
from plain.exceptions import ImproperlyConfigured

from .build import build
from .chores import chores
from .docs import docs
from .formatting import PlainContext
from .preflight import preflight_checks
from .registry import cli_registry
from .scaffold import create
from .settings import setting
from .shell import run, shell
from .urls import urls
from .utils import utils


@click.group()
def plain_cli():
    pass


plain_cli.add_command(docs)
plain_cli.add_command(preflight_checks)
plain_cli.add_command(create)
plain_cli.add_command(chores)
plain_cli.add_command(build)
plain_cli.add_command(utils)
plain_cli.add_command(urls)
plain_cli.add_command(setting)
plain_cli.add_command(shell)
plain_cli.add_command(run)


class CLIRegistryGroup(click.Group):
    """
    Click Group that exposes commands from the CLI registry.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cli_registry.import_modules()

    def list_commands(self, ctx):
        return sorted(cli_registry.get_commands().keys())

    def get_command(self, ctx, name):
        commands = cli_registry.get_commands()
        return commands.get(name)


class PlainCommandCollection(click.CommandCollection):
    context_class = PlainContext

    def __init__(self, *args, **kwargs):
        sources = []

        try:
            plain.runtime.setup()

            sources = [
                CLIRegistryGroup(),
                plain_cli,
            ]
        except plain.runtime.AppPathNotFound:
            # Allow some commands to work regardless of being in a valid app
            click.secho(
                "Plain `app` directory not found. Some commands may be missing.",
                fg="yellow",
                err=True,
            )

            sources = [
                plain_cli,
            ]
        except ImproperlyConfigured as e:
            # Show what was configured incorrectly and exit
            click.secho(
                str(e),
                fg="red",
                err=True,
            )

            exit(1)
        except Exception as e:
            # Show the exception and exit
            print("---")
            print(traceback.format_exc())
            print("---")

            click.secho(
                f"Error: {e}",
                fg="red",
                err=True,
            )

            exit(1)

        super().__init__(*args, **kwargs)

        self.sources = sources

    def get_command(self, ctx: Context, cmd_name: str) -> Command | None:
        cmd = super().get_command(ctx, cmd_name)
        if cmd:
            # Pass the formatting down to subcommands automatically
            cmd.context_class = self.context_class
        return cmd


cli = PlainCommandCollection()

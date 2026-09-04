from __future__ import annotations

import os
import sys
import traceback
from importlib.metadata import EntryPoint, entry_points, version
from typing import Any

import click
import plain.runtime
from click.core import Command, Context
from plain.exceptions import ImproperlyConfigured

from .agent import agent
from .changelog import changelog
from .check import check
from .chores import chores
from .docs import docs
from .formatting import PlainContext
from .install import install
from .memory import memory
from .preflight import preflight_cli
from .registry import cli_registry
from .request import request
from .scaffold import create
from .server import server
from .settings import settings
from .shell import shell
from .upgrade import upgrade
from .urls import urls
from .utils import utils


@click.group()
def plain_cli() -> None:
    pass


# Maps top-level command names to the PLAIN_ENV they imply. Set before
# plain.runtime.setup() runs so plain.dev's dotenv loader picks up the right
# `.env.<env>*` files for the active command. `plain env` isn't here — it runs
# without setup and sets its own PLAIN_ENV.
_PLAIN_ENV_DEFAULTS = {
    "dev": "dev",
    "test": "test",
}


plain_cli.add_command(check)
plain_cli.add_command(docs)
plain_cli.add_command(request)
plain_cli.add_command(memory)
plain_cli.add_command(agent)
plain_cli.add_command(preflight_cli)
plain_cli.add_command(create)
plain_cli.add_command(chores)
plain_cli.add_command(utils)
plain_cli.add_command(urls)
plain_cli.add_command(changelog)
plain_cli.add_command(settings)
plain_cli.add_command(shell)
plain_cli.add_command(install)
plain_cli.add_command(upgrade)
plain_cli.add_command(server)


class EntryPointCommands(click.Group):
    """Commands packages contribute through the `plain.cli` entry point group.

    Everything here runs *without* `plain.runtime.setup()` — being in this group
    is the definition of a command that has to work before the app can load.
    Entry points are only imported when one of their commands is actually asked
    for, so an installed package costs nothing until it is used.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._entry_points = {
            entry_point.name: entry_point
            for entry_point in entry_points(group="plain.cli")
        }

    def list_commands(self, ctx: Context) -> list[str]:
        return sorted(self._entry_points)

    def get_command(self, ctx: Context, cmd_name: str) -> Command | None:
        entry_point = self._entry_points.get(cmd_name)
        if entry_point is None:
            return None

        try:
            cmd = entry_point.load()
        except Exception as e:
            raise click.ClickException(
                f"The `{cmd_name}` command from {_entry_point_package(entry_point)} "
                f"could not be loaded ({entry_point.value}): {e}"
            ) from e

        cmd.without_runtime_setup = True
        return cmd


def _entry_point_package(entry_point: EntryPoint) -> str:
    """The installed package an entry point came from, for error messages."""
    if entry_point.dist:
        return entry_point.dist.name
    return "an unknown package"


class CLIRegistryGroup(click.Group):
    """
    Click Group that exposes commands from the CLI registry.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        cli_registry.import_modules()

    def list_commands(self, ctx: Context) -> list[str]:
        return sorted(cli_registry.get_commands().keys())

    def get_command(self, ctx: Context, cmd_name: str) -> Command | None:
        commands = cli_registry.get_commands()
        return commands.get(cmd_name)


class PlainCommandCollection(click.CommandCollection):
    context_class = PlainContext

    def __init__(self, *args: Any, **kwargs: Any):
        # Commands that don't need setup: built-ins first, so a package entry
        # point can never take over a built-in name.
        sources = [plain_cli, EntryPointCommands()]

        super().__init__(*args, **kwargs)
        self.sources = sources
        self._registry_group = None
        self._setup_attempted = False
        self._setup_error: Exception | None = None
        self._setup_warned = False

    def _load_registry(self) -> None:
        """Run setup() once, remembering a failure instead of raising it."""
        if self._setup_attempted:
            return

        self._setup_attempted = True

        try:
            plain.runtime.setup()
            self._registry_group = CLIRegistryGroup()
            # Add registry group to sources
            self.sources.insert(0, self._registry_group)
        except Exception as e:
            self._setup_error = e

    def _warn_once(self, message: str) -> None:
        """Warn that some commands are missing, however many times we're asked."""
        if self._setup_warned:
            return

        self._setup_warned = True
        click.secho(message, fg="yellow", err=True)

    def _ensure_registry_loaded(self, cmd_name: str, *, required: bool = True) -> None:
        """Lazy load the registry group (requires setup).

        `cmd_name` is the command that made us load the app, so a failure can
        say which one. A name that isn't a built-in could still be an app or
        package command, so we can't tell a typo from a real command until the
        registry loads — when it doesn't, the app's failure is the real answer.

        `required` is False when we're only listing commands for help. The
        registry would have added to that listing, but the built-ins are still
        worth showing — especially to someone trying to fix the app that just
        failed to load — so a failure there is a warning rather than an exit.
        """
        self._load_registry()

        error = self._setup_error
        if error is None:
            return

        if isinstance(error, plain.runtime.AppPathNotFound):
            # Allow built-in commands to work regardless of being in a valid app
            self._warn_once(
                "Plain `app` directory not found. Some commands may be missing."
            )
            return

        if not required:
            self._warn_once(
                f"App and package commands are missing — the app failed to load: {error}"
            )
            return

        if isinstance(error, ImproperlyConfigured):
            # Show what was configured incorrectly and exit
            click.secho(
                str(error),
                fg="red",
                err=True,
            )
            sys.exit(1)

        # Traceback on stderr too, so it stays directly above the error line
        # when output is piped or redirected.
        click.echo("".join(traceback.format_exception(error)), err=True)
        click.secho(
            f"Error loading the app, which `plain {cmd_name}` needs: {error}",
            fg="red",
            err=True,
        )
        sys.exit(1)

    def get_command(self, ctx: Context, cmd_name: str) -> Command | None:
        # Set PLAIN_ENV default before any setup runs so plain.dev's dotenv
        # loader picks up the right `.env.<env>*` files for this command.
        if env := _PLAIN_ENV_DEFAULTS.get(cmd_name):
            os.environ.setdefault("PLAIN_ENV", env)

        # Try built-in commands first
        cmd = super().get_command(ctx, cmd_name)

        if cmd is None:
            # Command not found in built-ins, try registry (requires setup)
            self._ensure_registry_loaded(cmd_name)
            cmd = super().get_command(ctx, cmd_name)
        elif not getattr(cmd, "without_runtime_setup", False):
            # Command found but needs setup - ensure registry is loaded
            self._ensure_registry_loaded(cmd_name)

        if cmd:
            # Pass the formatting down to subcommands automatically
            cmd.context_class = self.context_class
        return cmd

    def list_commands(self, ctx: Context) -> list[str]:
        # For help listing, we need to show registry commands too
        self._ensure_registry_loaded("--help", required=False)
        return super().list_commands(ctx)

    def format_commands(self, ctx: Context, formatter: Any) -> None:
        """Format commands with separate sections for common, core, and package commands."""
        self._ensure_registry_loaded("--help", required=False)

        # Get every command, remembering whether it is one of Plain's own
        commands = []
        for source in self.sources:
            for name in source.list_commands(ctx):
                cmd = source.get_command(ctx, name)
                if cmd is not None:
                    commands.append((name, cmd, source is plain_cli))

        if not commands:
            return

        # Get metadata from the registry (for shortcuts)
        shortcuts_metadata = cli_registry.get_shortcuts()

        # Separate commands into common, core, and package
        common_commands = []
        core_commands = []
        package_commands = []

        for name, cmd, is_core in commands:
            help_text = cmd.get_short_help_str(limit=200)

            # Check if command is marked as common via decorator
            is_common = getattr(cmd, "is_common_command", False)

            if is_common:
                # This is a common command
                # Add arrow notation if it's also a shortcut
                if name in shortcuts_metadata:
                    shortcut_for = shortcuts_metadata[name].shortcut_for
                    if shortcut_for:
                        alias_info = click.style(f"(→ {shortcut_for})", italic=True)
                        help_text = f"{help_text} {alias_info}"
                common_commands.append((name, help_text))
            elif is_core:
                core_commands.append((name, help_text))
            else:
                # From the registry or a `plain.cli` entry point
                package_commands.append((name, help_text))

        # Write common commands section if any exist
        if common_commands:
            with formatter.section("Common Commands"):
                formatter.write_dl(sorted(common_commands))

        # Write core commands section if any exist
        if core_commands:
            with formatter.section("Core Commands"):
                formatter.write_dl(sorted(core_commands))

        # Write package commands section if any exist
        if package_commands:
            with formatter.section("Package Commands"):
                formatter.write_dl(sorted(package_commands))


def _print_version(ctx: Context, param: click.Parameter, value: bool) -> None:
    if value:
        click.echo(version("plain"))
        ctx.exit()


cli = PlainCommandCollection(
    params=[
        click.Option(
            ["--version"],
            is_flag=True,
            expose_value=False,
            is_eager=True,
            callback=_print_version,
        )
    ]
)

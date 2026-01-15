from __future__ import annotations

import traceback
from typing import Any

import click
from click.core import Command, Context

import plain.runtime
from plain.exceptions import ImproperlyConfigured

from .agent import agent
from .build import build
from .changelog import changelog
from .chores import chores
from .docs import docs
from .formatting import PlainContext
from .install import install
from .preflight import preflight_cli
from .registry import cli_registry
from .request import request
from .scaffold import create
from .server import server
from .settings import settings
from .shell import run, shell
from .upgrade import upgrade
from .urls import urls
from .utils import utils


@click.group()
def plain_cli() -> None:
    pass


plain_cli.add_command(docs)
plain_cli.add_command(request)
plain_cli.add_command(agent)
plain_cli.add_command(preflight_cli)
plain_cli.add_command(create)
plain_cli.add_command(chores)
plain_cli.add_command(build)
plain_cli.add_command(utils)
plain_cli.add_command(urls)
plain_cli.add_command(changelog)
plain_cli.add_command(settings)
plain_cli.add_command(shell)
plain_cli.add_command(run)
plain_cli.add_command(install)
plain_cli.add_command(upgrade)
plain_cli.add_command(server)


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
        # Start with only built-in commands (no setup needed)
        sources = [plain_cli]

        super().__init__(*args, **kwargs)
        self.sources = sources
        self._registry_group = None
        self._setup_attempted = False

    def _ensure_registry_loaded(self) -> None:
        """Lazy load the registry group (requires setup)."""
        if self._registry_group is not None or self._setup_attempted:
            return

        self._setup_attempted = True

        try:
            plain.runtime.setup()
            self._registry_group = CLIRegistryGroup()
            # Add registry group to sources
            self.sources.insert(0, self._registry_group)
        except plain.runtime.AppPathNotFound:
            # Allow built-in commands to work regardless of being in a valid app
            click.secho(
                "Plain `app` directory not found. Some commands may be missing.",
                fg="yellow",
                err=True,
            )
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

    def get_command(self, ctx: Context, cmd_name: str) -> Command | None:
        # Try built-in commands first
        cmd = super().get_command(ctx, cmd_name)

        if cmd is None:
            # Command not found in built-ins, try registry (requires setup)
            self._ensure_registry_loaded()
            cmd = super().get_command(ctx, cmd_name)
        elif not getattr(cmd, "without_runtime_setup", False):
            # Command found but needs setup - ensure registry is loaded
            self._ensure_registry_loaded()

        if cmd:
            # Pass the formatting down to subcommands automatically
            cmd.context_class = self.context_class
        return cmd

    def list_commands(self, ctx: Context) -> list[str]:
        # For help listing, we need to show registry commands too
        self._ensure_registry_loaded()
        return super().list_commands(ctx)

    def format_commands(self, ctx: Context, formatter: Any) -> None:
        """Format commands with separate sections for common, core, and package commands."""
        self._ensure_registry_loaded()

        # Get all commands from both sources, tracking their source
        commands = []
        for source_index, source in enumerate(self.sources):
            for name in source.list_commands(ctx):
                cmd = source.get_command(ctx, name)
                if cmd is not None:
                    # source_index 0 = plain_cli (core), 1+ = registry (packages)
                    commands.append((name, cmd, source_index))

        if not commands:
            return

        # Get metadata from the registry (for shortcuts)
        shortcuts_metadata = cli_registry.get_shortcuts()

        # Separate commands into common, core, and package
        common_commands = []
        core_commands = []
        package_commands = []

        for name, cmd, source_index in commands:
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
            elif source_index == 0:
                # Package command (from registry, inserted at index 0)
                package_commands.append((name, help_text))
            else:
                # Core command (from plain_cli, at index 1)
                core_commands.append((name, help_text))

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


cli = PlainCommandCollection()

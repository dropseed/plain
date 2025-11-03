from __future__ import annotations

from typing import Any, NamedTuple

from plain.packages import packages_registry


class CommandMetadata(NamedTuple):
    """Metadata about a registered command."""

    cmd: Any
    shortcut_for: str | None = None
    is_common: bool = False


class CLIRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandMetadata] = {}

    def register_command(
        self,
        cmd: Any,
        name: str,
        shortcut_for: str | None = None,
        is_common: bool = False,
    ) -> None:
        """
        Register a CLI command or group with the specified name.

        Args:
            cmd: The click command or group to register
            name: The name to register the command under
            shortcut_for: Optional parent command this is a shortcut for (e.g., "models" for migrate)
            is_common: Whether this is a commonly used command to show in the "Common Commands" section
        """
        self._commands[name] = CommandMetadata(
            cmd=cmd, shortcut_for=shortcut_for, is_common=is_common
        )

    def import_modules(self) -> None:
        """
        Import modules from installed packages and app to trigger registration.
        """
        packages_registry.autodiscover_modules("cli", include_app=True)

    def get_commands(self) -> dict[str, Any]:
        """
        Get all registered commands (just the command objects, not metadata).
        """
        return {name: metadata.cmd for name, metadata in self._commands.items()}

    def get_commands_with_metadata(self) -> dict[str, CommandMetadata]:
        """
        Get all registered commands with their metadata.
        """
        return self._commands

    def get_shortcuts(self) -> dict[str, CommandMetadata]:
        """
        Get only commands that are shortcuts.
        """
        return {
            name: metadata
            for name, metadata in self._commands.items()
            if metadata.shortcut_for
        }

    def get_common_commands(self) -> dict[str, CommandMetadata]:
        """
        Get only commands that are marked as common.
        """
        return {
            name: metadata
            for name, metadata in self._commands.items()
            if metadata.is_common
        }

    def get_regular_commands(self) -> dict[str, CommandMetadata]:
        """
        Get only commands that are not common.
        """
        return {
            name: metadata
            for name, metadata in self._commands.items()
            if not metadata.is_common
        }


cli_registry = CLIRegistry()


def register_cli(
    name: str, shortcut_for: str | None = None, common: bool = False
) -> Any:
    """
    Register a CLI command or group with the given name.

    Args:
        name: The name to register the command under
        shortcut_for: Optional parent command this is a shortcut for.
                     For example, @register_cli("migrate", shortcut_for="models")
                     indicates that "plain migrate" is a shortcut for "plain models migrate"
        common: Whether this is a commonly used command to show in the "Common Commands" section

    Usage:
        # Register a regular command group
        @register_cli("users")
        @click.group()
        def users_cli():
            pass

        # Register a shortcut command
        @register_cli("migrate", shortcut_for="models", common=True)
        @click.command()
        def migrate():
            pass

        # Register a common command
        @register_cli("dev", common=True)
        @click.command()
        def dev():
            pass
    """

    def wrapper(cmd: Any) -> Any:
        cli_registry.register_command(
            cmd, name, shortcut_for=shortcut_for, is_common=common
        )
        return cmd

    return wrapper

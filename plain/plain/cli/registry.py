from __future__ import annotations

from typing import Any

from plain.packages import packages_registry


class CLIRegistry:
    def __init__(self):
        self._commands: dict[str, Any] = {}

    def register_command(self, cmd: Any, name: str) -> None:
        """
        Register a CLI command or group with the specified name.
        """
        self._commands[name] = cmd

    def import_modules(self) -> None:
        """
        Import modules from installed packages and app to trigger registration.
        """
        packages_registry.autodiscover_modules("cli", include_app=True)

    def get_commands(self) -> dict[str, Any]:
        """
        Get all registered commands.
        """
        return self._commands


cli_registry = CLIRegistry()


def register_cli(name: str) -> Any:
    """
    Register a CLI command or group with the given name.

    Usage:
        @register_cli("users")
        @click.group()
        def users_cli():
            pass
    """

    def wrapper(cmd: Any) -> Any:
        cli_registry.register_command(cmd, name)
        return cmd

    return wrapper

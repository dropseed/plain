from importlib import import_module
from importlib.util import find_spec

from plain.packages import packages_registry


class CLIRegistry:
    def __init__(self):
        self._commands = {}

    def register_command(self, cmd, name):
        """
        Register a CLI command or group with the specified name.
        """
        self._commands[name] = cmd

    def import_modules(self):
        """
        Import modules from installed packages and app to trigger registration.
        """
        # Import from installed packages
        for package_config in packages_registry.get_package_configs():
            import_name = f"{package_config.name}.cli"
            try:
                import_module(import_name)
            except ModuleNotFoundError:
                pass

        # Import from app
        import_name = "app.cli"
        if find_spec(import_name):
            try:
                import_module(import_name)
            except ModuleNotFoundError:
                pass

    def get_commands(self):
        """
        Get all registered commands.
        """
        return self._commands


cli_registry = CLIRegistry()


def register_cli(name):
    """
    Register a CLI command or group with the given name.

    Usage:
        @register_cli("users")
        @click.group()
        def users_cli():
            pass
    """

    def wrapper(cmd):
        cli_registry.register_command(cmd, name)
        return cmd

    return wrapper

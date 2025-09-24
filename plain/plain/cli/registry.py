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
        packages_registry.autodiscover_modules("cli", include_app=True)

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

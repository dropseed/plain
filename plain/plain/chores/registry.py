from importlib import import_module
from importlib.util import find_spec

from plain.packages import packages_registry


class Chore:
    def __init__(self, *, group, func):
        self.group = group
        self.func = func
        self.name = f"{group}.{func.__name__}"
        self.description = func.__doc__.strip() if func.__doc__ else ""

    def __str__(self):
        return self.name

    def run(self):
        """
        Run the chore.
        """
        return self.func()


class ChoresRegistry:
    def __init__(self):
        self._chores = {}

    def register_chore(self, chore):
        """
        Register a chore with the specified name.
        """
        self._chores[chore.func] = chore

    def import_modules(self):
        """
        Import modules from installed packages and app to trigger registration.
        """
        # Import from installed packages
        for package_config in packages_registry.get_package_configs():
            import_name = f"{package_config.name}.chores"
            try:
                import_module(import_name)
            except ModuleNotFoundError:
                pass

        # Import from app
        import_name = "app.chores"
        if find_spec(import_name):
            try:
                import_module(import_name)
            except ModuleNotFoundError:
                pass

    def get_chores(self):
        """
        Get all registered chores.
        """
        return list(self._chores.values())


chores_registry = ChoresRegistry()


def register_chore(group):
    """
    Register a chore with a given group.

    Usage:
        @register_chore("clear_expired")
        def clear_expired():
            pass
    """

    def wrapper(func):
        chore = Chore(group=group, func=func)
        chores_registry.register_chore(chore)
        return func

    return wrapper

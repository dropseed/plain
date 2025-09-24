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
        packages_registry.autodiscover_modules("chores", include_app=True)

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

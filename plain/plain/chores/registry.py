from __future__ import annotations

from types import FunctionType
from typing import Any

from plain.packages import packages_registry


class Chore:
    def __init__(self, *, group: str, func: FunctionType):
        self.group = group
        self.func = func
        self.name = f"{group}.{func.__name__}"
        self.description = func.__doc__.strip() if func.__doc__ else ""

    def __str__(self) -> str:
        return self.name

    def run(self) -> Any:
        """
        Run the chore.
        """
        return self.func()


class ChoresRegistry:
    def __init__(self):
        self._chores: dict[FunctionType, Chore] = {}

    def register_chore(self, chore: Chore) -> None:
        """
        Register a chore with the specified name.
        """
        self._chores[chore.func] = chore

    def import_modules(self) -> None:
        """
        Import modules from installed packages and app to trigger registration.
        """
        packages_registry.autodiscover_modules("chores", include_app=True)

    def get_chores(self) -> list[Chore]:
        """
        Get all registered chores.
        """
        return list(self._chores.values())


chores_registry = ChoresRegistry()


def register_chore(group: str) -> Any:
    """
    Register a chore with a given group.

    Usage:
        @register_chore("clear_expired")
        def clear_expired():
            pass
    """

    def wrapper(func: FunctionType) -> FunctionType:
        chore = Chore(group=group, func=func)
        chores_registry.register_chore(chore)
        return func

    return wrapper

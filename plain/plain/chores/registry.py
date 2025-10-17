from __future__ import annotations

from plain.packages import packages_registry

from .core import Chore


class ChoresRegistry:
    def __init__(self) -> None:
        self._chores: dict[str, type[Chore]] = {}

    def register_chore(self, chore_class: type[Chore]) -> None:
        """
        Register a chore class.

        Args:
            chore_class: A Chore subclass to register
        """
        name = f"{chore_class.__module__}.{chore_class.__qualname__}"
        self._chores[name] = chore_class

    def import_modules(self) -> None:
        """
        Import modules from installed packages and app to trigger registration.
        """
        packages_registry.autodiscover_modules("chores", include_app=True)

    def get_chores(self) -> list[type[Chore]]:
        """
        Get all registered chore classes.
        """
        return list(self._chores.values())


chores_registry = ChoresRegistry()


def register_chore(cls: type[Chore]) -> type[Chore]:
    """
    Decorator to register a chore class.

    Usage:
        @register_chore
        class ClearExpired(Chore):
            def run(self):
                return "Done!"
    """
    chores_registry.register_chore(cls)
    return cls

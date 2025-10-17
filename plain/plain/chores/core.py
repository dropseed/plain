from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Chore(ABC):
    """
    Abstract base class for chores.

    Subclasses must implement:
    - run() method

    Example:
        @register_chore
        class ClearExpired(Chore):
            '''Delete sessions that have expired.'''

            def run(self):
                # ... implementation
                return "10 sessions deleted"
    """

    @property
    def name(self) -> str:
        """Get the full module path and class name of the chore."""
        return f"{self.__class__.__module__}.{self.__class__.__qualname__}"

    @property
    def description(self) -> str:
        """Get the description from the class docstring."""
        if self.__class__.__doc__:
            return self.__class__.__doc__.strip()
        return ""

    def __str__(self) -> str:
        return self.name

    @abstractmethod
    def run(self) -> Any:
        """Run the chore. Must be implemented by subclasses."""
        pass

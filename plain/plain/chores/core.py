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

    @abstractmethod
    def run(self) -> Any:
        """Run the chore. Must be implemented by subclasses."""
        pass

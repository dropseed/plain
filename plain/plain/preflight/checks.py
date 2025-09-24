from abc import ABC, abstractmethod


class PreflightCheck(ABC):
    """Base class for all preflight checks."""

    @abstractmethod
    def run(self):
        """Must return a list of Warning/Error results."""
        raise NotImplementedError

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..results import AuditResult
    from ..scanner import Scanner


class Audit(ABC):
    """Base class for security check audits."""

    name: str
    slug: str  # URL-friendly identifier for disabling audits
    required: bool = True  # Whether this audit is required for all sites
    description: str | None = None  # Optional description shown in verbose mode

    @abstractmethod
    def check(self, scanner: Scanner) -> AuditResult:
        """Run checks for this audit and return results."""
        pass

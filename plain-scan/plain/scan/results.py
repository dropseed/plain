from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .metadata import ScanMetadata


@dataclass
class CheckResult:
    """Result of a single security check."""

    name: str
    passed: bool
    message: str
    nested_checks: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
        }
        if self.nested_checks:
            result["nested_checks"] = [check.to_dict() for check in self.nested_checks]
        return result


@dataclass
class AuditResult:
    """Result of an audit of security checks."""

    name: str
    detected: bool
    checks: list[CheckResult] = field(default_factory=list)
    required: bool = True  # Whether this audit is required for all sites
    disabled: bool = False  # True if user disabled this audit via --disable
    description: str | None = None  # Optional description of what this audit checks

    @property
    def passed(self) -> bool:
        """Audit passes if detected and all checks pass, or if optional and not detected."""
        # Disabled audits are excluded from pass/fail logic
        if self.disabled:
            return True
        if not self.detected:
            # Optional audits pass even when not detected
            return not self.required
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "name": self.name,
            "detected": self.detected,
            "required": self.required,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
        }
        if self.disabled:
            result["disabled"] = self.disabled
        if self.description:
            result["description"] = self.description
        return result


@dataclass
class ScanResult:
    """Complete scan results for a URL."""

    url: str
    audits: list[AuditResult] = field(default_factory=list)
    metadata: ScanMetadata | None = None

    @property
    def passed(self) -> bool:
        """Scan passes if all audits pass (including required audits being detected)."""
        if not self.audits:
            return False
        return all(audit.passed for audit in self.audits)

    @property
    def passed_count(self) -> int:
        """Count of audits that passed (excluding disabled audits)."""
        return sum(1 for audit in self.audits if audit.passed and not audit.disabled)

    @property
    def failed_count(self) -> int:
        """Count of audits that failed (excluding disabled audits)."""
        return sum(
            1 for audit in self.audits if not audit.passed and not audit.disabled
        )

    @property
    def total_count(self) -> int:
        """Total count of audits (excluding disabled audits)."""
        return sum(1 for audit in self.audits if not audit.disabled)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "url": self.url,
            "passed": self.passed,
            "audits": [audit.to_dict() for audit in self.audits],
        }
        if self.metadata:
            result["metadata"] = self.metadata.to_dict()
        return result

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

    @classmethod
    def from_dict(cls, data: dict) -> CheckResult:
        """Reconstruct CheckResult from dictionary."""
        return cls(
            name=data["name"],
            passed=data["passed"],
            message=data["message"],
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
        }


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

    @classmethod
    def from_dict(cls, data: dict) -> AuditResult:
        """Reconstruct AuditResult from dictionary."""
        checks = [CheckResult.from_dict(c) for c in data.get("checks", [])]
        return cls(
            name=data["name"],
            detected=data["detected"],
            checks=checks,
            required=data.get("required", True),
            disabled=data.get("disabled", False),
            description=data.get("description"),
        )

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

    @classmethod
    def from_dict(cls, data: dict) -> ScanResult:
        """Reconstruct ScanResult from dictionary."""
        from .metadata import ScanMetadata

        audits = [AuditResult.from_dict(a) for a in data.get("audits", [])]
        metadata = None
        if "metadata" in data:
            metadata = ScanMetadata.from_dict(data["metadata"])
        return cls(
            url=data["url"],
            audits=audits,
            metadata=metadata,
        )

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

from __future__ import annotations

from typing import TYPE_CHECKING

from ..results import AuditResult, CheckResult
from .base import Audit

if TYPE_CHECKING:
    from ..scanner import Scanner


class ContentTypeOptionsAudit(Audit):
    """Content type options header checks."""

    name = "Content Type Options"
    slug = "content-type-options"
    description = "Prevents browsers from MIME-sniffing responses away from the declared content type. See: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Content-Type-Options"

    def check(self, scanner: Scanner) -> AuditResult:
        """Check if X-Content-Type-Options header is present and configured properly."""
        response = scanner.fetch()

        # Check if header is present
        header = response.headers.get("X-Content-Type-Options")

        if not header:
            # Header not detected
            return AuditResult(
                name=self.name,
                detected=False,
                required=self.required,
                checks=[],
                description=self.description,
            )

        # Header detected - validate value
        checks = [
            self._check_nosniff(header),
        ]

        return AuditResult(
            name=self.name,
            detected=True,
            required=self.required,
            checks=checks,
            description=self.description,
        )

    def _check_nosniff(self, header: str) -> CheckResult:
        """Check if X-Content-Type-Options is set to nosniff."""
        header_value = header.strip().lower()

        if header_value == "nosniff":
            return CheckResult(
                name="nosniff",
                passed=True,
                message="X-Content-Type-Options is set to nosniff",
            )

        return CheckResult(
            name="nosniff",
            passed=False,
            message=f"X-Content-Type-Options has invalid value: '{header}' (expected: nosniff)",
        )

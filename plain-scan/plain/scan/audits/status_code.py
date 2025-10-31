from __future__ import annotations

from typing import TYPE_CHECKING

from ..results import AuditResult, CheckResult
from .base import Audit

if TYPE_CHECKING:
    from ..scanner import Scanner


class StatusCodeAudit(Audit):
    """HTTP status code checks."""

    name = "HTTP Status Code"
    slug = "status-code"
    description = "Checks that the server returns a successful HTTP status code and not an error response."
    required = True  # Server errors are always a problem

    def check(self, scanner: Scanner) -> AuditResult:
        """Check if the final response has a valid status code."""
        response = scanner.fetch()

        # Get status code from response
        status_code = response.status_code if response else None

        if status_code is None:
            return AuditResult(
                name=self.name,
                detected=True,
                required=self.required,
                checks=[
                    CheckResult(
                        name="status-code",
                        passed=False,
                        message="Unable to determine HTTP status code",
                    )
                ],
                description=self.description,
            )

        # Check for server errors (5xx)
        if 500 <= status_code < 600:
            return AuditResult(
                name=self.name,
                detected=True,
                required=self.required,
                checks=[
                    CheckResult(
                        name="status-code",
                        passed=False,
                        message=f"Server returned {status_code} error - cannot perform complete security audit",
                    )
                ],
                description=self.description,
            )

        # Check for client errors (4xx) - informational, not required to pass
        if 400 <= status_code < 500:
            return AuditResult(
                name=self.name,
                detected=True,
                required=False,  # 4xx might be expected (like 404 for a test page)
                checks=[
                    CheckResult(
                        name="status-code",
                        passed=False,
                        message=f"Server returned {status_code} client error",
                    )
                ],
                description=self.description,
            )

        # Success (2xx) or redirect (3xx) - all good
        return AuditResult(
            name=self.name,
            detected=True,
            required=self.required,
            checks=[
                CheckResult(
                    name="status-code",
                    passed=True,
                    message=f"Server returned {status_code} status code",
                )
            ],
            description=self.description,
        )

from __future__ import annotations

from typing import TYPE_CHECKING

from ..results import AuditResult, CheckResult
from .base import Audit

if TYPE_CHECKING:
    from ..scanner import Scanner


class CORSAudit(Audit):
    """CORS (Cross-Origin Resource Sharing) security checks."""

    name = "Cross-Origin Resource Sharing (CORS)"
    slug = "cors"
    required = False  # CORS is only needed for cross-origin API endpoints
    description = "Checks for Cross-Origin Resource Sharing misconfigurations that could allow unauthorized access to resources. See: https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS"

    def check(self, scanner: Scanner) -> AuditResult:
        """Check if CORS is configured securely."""
        response = scanner.fetch()

        # Check for CORS headers
        allow_origin = response.headers.get("Access-Control-Allow-Origin")
        allow_credentials = response.headers.get("Access-Control-Allow-Credentials")
        vary_header = response.headers.get("Vary")

        if not allow_origin:
            # CORS not detected
            return AuditResult(
                name=self.name,
                detected=False,
                required=self.required,
                checks=[],
                description=self.description,
            )

        # CORS detected - run security checks
        checks = [
            self._check_wildcard_with_credentials(allow_origin, allow_credentials),
            self._check_null_origin(allow_origin),
            self._check_vary_header(allow_origin, vary_header),
        ]

        return AuditResult(
            name=self.name,
            detected=True,
            required=self.required,
            checks=checks,
            description=self.description,
        )

    def _check_wildcard_with_credentials(
        self, allow_origin: str, allow_credentials: str | None
    ) -> CheckResult:
        """Check for dangerous * origin with credentials."""
        is_wildcard = allow_origin.strip() == "*"
        allows_credentials = (
            allow_credentials and allow_credentials.strip().lower() == "true"
        )

        if is_wildcard and allows_credentials:
            return CheckResult(
                name="wildcard-credentials",
                passed=False,
                message="CORS allows all origins (*) with credentials (major security risk)",
            )

        if is_wildcard:
            return CheckResult(
                name="wildcard-credentials",
                passed=True,
                message="CORS allows all origins (*) without credentials (acceptable for public resources)",
            )

        return CheckResult(
            name="wildcard-credentials",
            passed=True,
            message="CORS origin is not set to wildcard",
        )

    def _check_null_origin(self, allow_origin: str) -> CheckResult:
        """Check for dangerous null origin."""
        if allow_origin.strip().lower() == "null":
            return CheckResult(
                name="null-origin",
                passed=False,
                message="CORS allows 'null' origin (can be exploited by sandboxed iframes)",
            )

        return CheckResult(
            name="null-origin",
            passed=True,
            message="CORS does not allow null origin",
        )

    def _check_vary_header(
        self, allow_origin: str, vary_header: str | None
    ) -> CheckResult:
        """Check for Vary: Origin header to prevent cache poisoning."""
        # Wildcard doesn't need Vary header since it doesn't vary by origin
        if allow_origin.strip() == "*":
            return CheckResult(
                name="vary-header",
                passed=True,
                message="Vary header not required for wildcard origin",
            )

        # For specific origins, Vary: Origin is needed to prevent cache poisoning
        if not vary_header:
            return CheckResult(
                name="vary-header",
                passed=False,
                message="Missing 'Vary: Origin' header (required to prevent cache poisoning when using specific origins)",
            )

        # Check if Origin is in the Vary header
        vary_values = [v.strip().lower() for v in vary_header.split(",")]
        if "origin" not in vary_values:
            return CheckResult(
                name="vary-header",
                passed=False,
                message=f"'Vary' header present but missing 'Origin' value (found: {vary_header})",
            )

        return CheckResult(
            name="vary-header",
            passed=True,
            message="Vary: Origin header correctly set",
        )

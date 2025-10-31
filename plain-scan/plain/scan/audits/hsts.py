from __future__ import annotations

from typing import TYPE_CHECKING

from ..results import AuditResult, CheckResult
from .base import Audit

if TYPE_CHECKING:
    from ..scanner import Scanner


class HSTSAudit(Audit):
    """HTTP Strict Transport Security checks."""

    name = "HTTP Strict Transport Security (HSTS)"
    slug = "hsts"
    description = "Ensures HSTS is configured to force HTTPS connections and protect against downgrade attacks. See: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Strict-Transport-Security"

    def check(self, scanner: Scanner) -> AuditResult:
        """Check if HSTS is present and configured properly."""
        response = scanner.fetch()

        # Check if HSTS header is present
        hsts_header = response.headers.get("Strict-Transport-Security")

        if not hsts_header:
            # HSTS header not detected
            return AuditResult(
                name=self.name,
                detected=False,
                required=self.required,
                checks=[],
                description=self.description,
            )

        directives = self._parse_directives(hsts_header)

        # HSTS header detected - run nested checks
        checks = [
            self._check_max_age(directives),
            self._check_include_subdomains(directives),
            self._check_preload(directives),
        ]

        return AuditResult(
            name=self.name,
            detected=True,
            required=self.required,
            checks=checks,
            description=self.description,
        )

    def _check_max_age(self, directives: dict[str, str | None]) -> CheckResult:
        """Check if HSTS max-age is set to a reasonable value."""
        # Parse max-age from header
        max_age = None
        value = directives.get("max-age")
        if value is not None:
            try:
                max_age = int(value)
            except ValueError:
                max_age = None

        if max_age is None:
            return CheckResult(
                name="max-age",
                passed=False,
                message="HSTS header missing max-age directive",
            )

        # Recommended minimum is 1 year (31536000 seconds)
        min_recommended = 31536000
        if max_age < min_recommended:
            return CheckResult(
                name="max-age",
                passed=False,
                message=f"HSTS max-age is {max_age} seconds (recommended minimum: {min_recommended})",
            )

        return CheckResult(
            name="max-age",
            passed=True,
            message=f"HSTS max-age is {max_age} seconds",
        )

    def _check_include_subdomains(
        self, directives: dict[str, str | None]
    ) -> CheckResult:
        """Ensure includeSubDomains directive is present."""
        if "includesubdomains" in directives:
            return CheckResult(
                name="include-subdomains",
                passed=True,
                message="HSTS applies to all subdomains",
            )

        return CheckResult(
            name="include-subdomains",
            passed=False,
            message="HSTS missing includeSubDomains directive",
        )

    def _check_preload(self, directives: dict[str, str | None]) -> CheckResult:
        """Check for preload directive to enable HSTS preload list eligibility."""
        if "preload" in directives:
            return CheckResult(
                name="preload",
                passed=True,
                message="HSTS preload directive present",
            )

        return CheckResult(
            name="preload",
            passed=False,
            message="HSTS missing preload directive (required for browser preload list)",
        )

    def _parse_directives(self, header: str) -> dict[str, str | None]:
        """Parse HSTS header directives into a dictionary."""
        directives: dict[str, str | None] = {}
        for directive in header.split(";"):
            directive = directive.strip()
            if not directive:
                continue

            if "=" in directive:
                key, value = directive.split("=", 1)
                directives[key.strip().lower()] = value.strip()
            else:
                directives[directive.strip().lower()] = None

        return directives

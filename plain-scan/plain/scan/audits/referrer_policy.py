from __future__ import annotations

from typing import TYPE_CHECKING

from ..results import AuditResult, CheckResult
from .base import Audit

if TYPE_CHECKING:
    from ..scanner import Scanner


class ReferrerPolicyAudit(Audit):
    """Referrer-Policy header checks."""

    name = "Referrer-Policy"
    slug = "referrer-policy"
    required = False  # Privacy-focused rather than critical security
    description = "Controls how much referrer information is sent with requests to protect user privacy. See: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Referrer-Policy"

    def check(self, scanner: Scanner) -> AuditResult:
        """Check if Referrer-Policy header is present and configured securely."""
        response = scanner.fetch()

        # Check if header is present
        header = response.headers.get("Referrer-Policy")

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
            self._check_policy_value(header),
        ]

        return AuditResult(
            name=self.name,
            detected=True,
            required=self.required,
            checks=checks,
            description=self.description,
        )

    def _check_policy_value(self, header: str) -> CheckResult:
        """Check if Referrer-Policy uses a secure value.

        For fallback chains (comma-separated values), the rightmost value
        is the preferred policy used by modern browsers, with earlier values
        as fallbacks for older browsers.
        """
        # Can have multiple comma-separated values (fallback chain)
        policies = [p.strip().lower() for p in header.split(",")]

        # Secure/recommended policies
        secure_policies = {
            "no-referrer",
            "strict-origin",
            "strict-origin-when-cross-origin",
            "same-origin",
        }

        # Acceptable but less ideal (OK for most sites)
        # Note: no-referrer-when-downgrade is the browser default and used by many
        # security-conscious sites. It's not a security issue, just less privacy-preserving.
        acceptable_policies = {
            "origin",
            "origin-when-cross-origin",
            "no-referrer-when-downgrade",
        }

        # Permissive/problematic policies
        permissive_policies = {
            "unsafe-url",
        }

        # Check the last (preferred) policy in the chain
        primary_policy = policies[-1]

        if primary_policy in secure_policies:
            return CheckResult(
                name="policy",
                passed=True,
                message=f"Referrer-Policy uses secure value: {primary_policy}",
            )

        if primary_policy in acceptable_policies:
            # Acceptable but not ideal
            return CheckResult(
                name="policy",
                passed=True,
                message=f"Referrer-Policy uses acceptable value: {primary_policy}",
            )

        if primary_policy in permissive_policies:
            return CheckResult(
                name="policy",
                passed=False,
                message=f"Referrer-Policy uses permissive value that leaks information: {primary_policy}",
            )

        # Unknown or invalid policy
        return CheckResult(
            name="policy",
            passed=False,
            message=f"Referrer-Policy has unrecognized value: {primary_policy}",
        )

from __future__ import annotations

from typing import TYPE_CHECKING

from ..results import AuditResult, CheckResult
from .base import Audit

if TYPE_CHECKING:
    from ..scanner import Scanner


class FrameOptionsAudit(Audit):
    """Frame options header checks."""

    name = "Frame Options"
    slug = "frame-options"
    description = "Protects against clickjacking attacks by controlling whether the site can be framed. CSP frame-ancestors is the modern alternative. See: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Frame-Options"

    def check(self, scanner: Scanner) -> AuditResult:
        """Check if X-Frame-Options or CSP frame-ancestors is configured."""
        response = scanner.fetch()

        # Check for X-Frame-Options header
        xfo_header = response.headers.get("X-Frame-Options")

        # Check for CSP frame-ancestors as modern alternative
        csp_header = response.headers.get("Content-Security-Policy")
        frame_ancestors = []
        if csp_header:
            frame_ancestors = self._extract_frame_ancestors(csp_header)
        has_frame_ancestors = bool(frame_ancestors)

        if not xfo_header and not has_frame_ancestors:
            # Neither protection detected
            return AuditResult(
                name=self.name,
                detected=False,
                required=self.required,
                checks=[],
                description=self.description,
            )

        checks = []

        # Check X-Frame-Options if present
        if xfo_header:
            checks.append(self._check_xfo_value(xfo_header))

        if has_frame_ancestors:
            checks.append(self._check_frame_ancestors(frame_ancestors))

        return AuditResult(
            name=self.name,
            detected=True,
            required=self.required,
            checks=checks,
            description=self.description,
        )

    def _check_xfo_value(self, header: str) -> CheckResult:
        """Check if X-Frame-Options has a valid value."""
        header_value = header.strip().upper()

        valid_values = ["DENY", "SAMEORIGIN"]

        # ALLOW-FROM is deprecated but we'll acknowledge it
        if header_value in valid_values:
            return CheckResult(
                name="value",
                passed=True,
                message=f"X-Frame-Options is set to {header_value}",
            )

        if header_value.startswith("ALLOW-FROM"):
            return CheckResult(
                name="value",
                passed=False,
                message="X-Frame-Options uses deprecated ALLOW-FROM syntax (use CSP frame-ancestors instead)",
            )

        return CheckResult(
            name="value",
            passed=False,
            message=f"X-Frame-Options has invalid value: '{header}' (expected: DENY or SAMEORIGIN)",
        )

    def _extract_frame_ancestors(self, csp_header: str) -> list[str]:
        """Extract frame-ancestors directive values from CSP."""
        for directive in csp_header.split(";"):
            directive = directive.strip()
            if not directive:
                continue

            parts = directive.split()
            if not parts:
                continue

            if parts[0].lower() == "frame-ancestors":
                return parts[1:]

        return []

    def _check_frame_ancestors(self, values: list[str]) -> CheckResult:
        """Validate frame-ancestors directive restricts embedding safely."""
        normalized = [value.strip() for value in values if value.strip()]

        if not normalized:
            return CheckResult(
                name="csp-frame-ancestors",
                passed=False,
                message="frame-ancestors directive is present but empty",
            )

        violations: list[str] = []
        saw_none = False
        for value in normalized:
            original = value.strip()
            original_lower = original.lower()
            stripped = original.strip('"').strip("'")
            lower = stripped.lower()

            if stripped == "*":
                violations.append("allows any origin (*)")
                continue

            if lower == "none":
                saw_none = True
                continue

            if lower == "self":
                continue

            if lower.startswith("http:"):
                violations.append(f"allows insecure origin {stripped}")
                continue

            if lower.startswith("https://"):
                continue

            if lower.startswith("https:"):
                # scheme-only https: still allows all HTTPS origins
                violations.append(
                    "uses scheme-only https: fallback (overly permissive)"
                )
                continue

            if original_lower.startswith("'nonce-") or original_lower.startswith(
                "'sha"
            ):
                violations.append(
                    f"contains unsupported token for frame-ancestors {stripped}"
                )
                continue

            if original_lower.startswith("'"):
                violations.append(f"contains unsupported keyword {stripped}")
                continue

            violations.append(f"contains unrecognized token {stripped}")

        if saw_none and len(normalized) > 1:
            violations.append("'none' must not be combined with other sources")

        if violations:
            return CheckResult(
                name="csp-frame-ancestors",
                passed=False,
                message="frame-ancestors is too permissive: " + "; ".join(violations),
            )

        return CheckResult(
            name="csp-frame-ancestors",
            passed=True,
            message="frame-ancestors restricts embedding to trusted origins",
        )

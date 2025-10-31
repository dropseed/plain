from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

import requests

from ..results import AuditResult, CheckResult
from .base import Audit

if TYPE_CHECKING:
    from ..scanner import Scanner


class RedirectsAudit(Audit):
    """Redirect hygiene checks."""

    name = "Redirects"
    slug = "redirects"
    description = "Validates redirect configuration including HTTP to HTTPS upgrades, redirect chains, and URL canonicalization."

    def check(self, scanner: Scanner) -> AuditResult:
        """Check redirect configuration and hygiene."""
        response = scanner.fetch()

        # Check if any redirects occurred
        if not response.history:
            # No redirects - but we still run checks on the final URL
            checks = [
                self._check_final_url_https(scanner.url, response.url),
                self._check_trailing_slash_redirect(scanner.url, response),
            ]

            return AuditResult(
                name=self.name,
                detected=True,
                required=self.required,
                checks=checks,
                description=self.description,
            )

        # Redirects occurred - run all checks
        checks = [
            self._check_http_to_https(scanner.url, response),
            self._check_redirect_chain_length(response),
            self._check_final_url_https(scanner.url, response.url),
            self._check_cross_origin_redirects(scanner.url, response),
            self._check_status_codes(response),
            self._check_trailing_slash_redirect(scanner.url, response),
        ]

        return AuditResult(
            name=self.name,
            detected=True,
            required=self.required,
            checks=checks,
            description=self.description,
        )

    def _check_http_to_https(
        self, original_url: str, response: requests.Response
    ) -> CheckResult:
        """Check if HTTP redirects to HTTPS."""
        original_parsed = urlparse(original_url)

        # Only check if original URL was HTTP
        if original_parsed.scheme != "http":
            return CheckResult(
                name="http-to-https",
                passed=True,
                message="Original URL is already HTTPS",
            )

        # Check if we ended up on HTTPS
        final_parsed = urlparse(response.url)
        if final_parsed.scheme == "https":
            return CheckResult(
                name="http-to-https",
                passed=True,
                message="HTTP successfully redirects to HTTPS",
            )

        return CheckResult(
            name="http-to-https",
            passed=False,
            message="HTTP does not redirect to HTTPS",
        )

    def _check_redirect_chain_length(self, response: requests.Response) -> CheckResult:
        """Check that redirect chain is not too long."""
        redirect_count = len(response.history)

        # More than 3 redirects is generally excessive
        max_redirects = 3

        if redirect_count > max_redirects:
            return CheckResult(
                name="redirect-chain",
                passed=False,
                message=f"Redirect chain has {redirect_count} redirects (recommended maximum: {max_redirects})",
            )

        return CheckResult(
            name="redirect-chain",
            passed=True,
            message=f"Redirect chain has {redirect_count} redirect(s)",
        )

    def _check_final_url_https(self, original_url: str, final_url: str) -> CheckResult:
        """Check that final URL is HTTPS."""
        final_parsed = urlparse(final_url)

        if final_parsed.scheme == "https":
            return CheckResult(
                name="final-url-https",
                passed=True,
                message="Final URL uses HTTPS",
            )

        # Only fail if the original URL was HTTP (expecting an upgrade)
        original_parsed = urlparse(original_url)
        if original_parsed.scheme == "http":
            return CheckResult(
                name="final-url-https",
                passed=False,
                message=f"Final URL uses {final_parsed.scheme} instead of HTTPS",
            )

        # Original was HTTPS, final is not HTTPS - this is bad (downgrade)
        return CheckResult(
            name="final-url-https",
            passed=False,
            message=f"HTTPS was downgraded to {final_parsed.scheme}",
        )

    def _check_cross_origin_redirects(
        self, original_url: str, response: requests.Response
    ) -> CheckResult:
        """
        Check for problematic cross-origin redirects.

        Mozilla Observatory's approach: Only fail if HTTP redirects to a different host on HTTPS.
        This prevents HSTS from protecting the initial HTTP request.

        HTTPS->HTTPS redirects to different hosts (like www canonicalization) are acceptable.
        """
        original_parsed = urlparse(original_url)

        # Only check if we started with HTTP
        if original_parsed.scheme != "http":
            return CheckResult(
                name="cross-origin-redirects",
                passed=True,
                message="Original URL is already HTTPS (cross-origin redirects acceptable)",
            )

        # Check if first redirect is to HTTPS on a different host
        if response.history:
            first_redirect = response.history[0]
            first_redirect_parsed = urlparse(first_redirect.url)

            # If first redirect is HTTP->HTTPS and changes host, this prevents HSTS
            if (
                first_redirect_parsed.scheme == "https"
                and first_redirect_parsed.netloc != original_parsed.netloc
            ):
                return CheckResult(
                    name="cross-origin-redirects",
                    passed=False,
                    message=f"HTTP to HTTPS redirect changes host to {first_redirect_parsed.netloc} (prevents HSTS on initial request)",
                )

        # Check final URL
        final_parsed = urlparse(response.url)
        if final_parsed.netloc != original_parsed.netloc:
            # Cross-origin but passed the checks above
            return CheckResult(
                name="cross-origin-redirects",
                passed=True,
                message=f"Cross-origin redirect to {final_parsed.netloc} is acceptable",
            )

        return CheckResult(
            name="cross-origin-redirects",
            passed=True,
            message="All redirects stay on the same domain",
        )

    def _check_status_codes(self, response: requests.Response) -> CheckResult:
        """Check that redirects use appropriate status codes."""
        # Valid redirect status codes: 301, 302, 303, 307, 308
        # Preferred: 301 (permanent), 302/307 (temporary), 308 (permanent, preserves method)
        valid_codes = {301, 302, 303, 307, 308}
        invalid_redirects = []

        for redirect_response in response.history:
            status_code = redirect_response.status_code
            if status_code not in valid_codes:
                invalid_redirects.append(f"{redirect_response.url} ({status_code})")

        if invalid_redirects:
            return CheckResult(
                name="redirect-status-codes",
                passed=False,
                message=f"Invalid redirect status codes found: {', '.join(invalid_redirects)}",
            )

        return CheckResult(
            name="redirect-status-codes",
            passed=True,
            message=f"All {len(response.history)} redirect(s) use valid status codes",
        )

    def _check_trailing_slash_redirect(
        self, original_url: str, response: requests.Response
    ) -> CheckResult:
        """Check if redirect is just adding/removing a trailing slash."""
        if not response.history:
            return CheckResult(
                name="trailing-slash-redirect",
                passed=True,
                message="No redirects occurred",
            )

        original_parsed = urlparse(original_url)
        final_parsed = urlparse(response.url)

        # Check if everything is the same except trailing slash
        if (
            original_parsed.scheme == final_parsed.scheme
            and original_parsed.netloc == final_parsed.netloc
            and original_parsed.params == final_parsed.params
            and original_parsed.query == final_parsed.query
            and original_parsed.fragment == final_parsed.fragment
        ):
            # Check if paths differ only by trailing slash
            orig_path = original_parsed.path
            final_path = final_parsed.path

            if orig_path.rstrip("/") == final_path.rstrip("/"):
                # It's a trailing slash redirect
                if orig_path.endswith("/") and not final_path.endswith("/"):
                    return CheckResult(
                        name="trailing-slash-redirect",
                        passed=False,
                        message="Unnecessary redirect removes trailing slash",
                    )
                elif not orig_path.endswith("/") and final_path.endswith("/"):
                    return CheckResult(
                        name="trailing-slash-redirect",
                        passed=False,
                        message="Unnecessary redirect adds trailing slash",
                    )

        return CheckResult(
            name="trailing-slash-redirect",
            passed=True,
            message="No trailing slash redirects detected",
        )

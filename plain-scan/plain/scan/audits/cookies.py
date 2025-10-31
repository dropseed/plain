from __future__ import annotations

from typing import TYPE_CHECKING

from ..results import AuditResult, CheckResult
from .base import Audit

if TYPE_CHECKING:
    from ..scanner import Scanner


class CookiesAudit(Audit):
    """Cookie security checks."""

    name = "Cookies"
    slug = "cookies"
    required = False  # Only relevant when cookies are actually issued
    description = "Validates cookie security attributes including Secure, HttpOnly, and SameSite to protect against XSS and CSRF attacks. See: https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies"

    def check(self, scanner: Scanner) -> AuditResult:
        """Check if cookies are configured securely."""
        response = scanner.fetch()

        # Get all Set-Cookie headers
        # Note: requests library stores these in response.headers but only returns the last one
        # We need to use response.raw to get all of them
        cookies = []

        # Try to get cookies from response.cookies (CookieJar)
        if response.cookies:
            for cookie in response.cookies:
                # SameSite can be in _rest as either "SameSite" or "samesite" (case-insensitive)
                samesite = None
                if hasattr(cookie, "_rest") and cookie._rest:
                    for key in cookie._rest:
                        if key.lower() == "samesite":
                            samesite = cookie._rest[key]
                            break

                cookies.append(
                    {
                        "name": cookie.name,
                        "secure": cookie.secure,
                        "httponly": hasattr(cookie, "_rest")
                        and "HttpOnly" in cookie._rest,
                        "samesite": samesite,
                    }
                )

        if not cookies:
            # No cookies detected
            return AuditResult(
                name=self.name,
                detected=False,
                required=self.required,
                checks=[],
                description=self.description,
            )

        # Cookies detected - run security checks
        checks = [
            self._check_secure_flag(cookies),
            self._check_httponly_flag(cookies),
            self._check_samesite_attribute(cookies),
        ]

        return AuditResult(
            name=self.name,
            detected=True,
            required=self.required,
            checks=checks,
            description=self.description,
        )

    def _check_secure_flag(self, cookies: list[dict]) -> CheckResult:
        """Check if cookies have Secure flag."""
        insecure_cookies = [c["name"] for c in cookies if not c["secure"]]

        if insecure_cookies:
            return CheckResult(
                name="secure",
                passed=False,
                message=f"Cookies missing Secure flag: {', '.join(insecure_cookies)}",
            )

        return CheckResult(
            name="secure",
            passed=True,
            message=f"All {len(cookies)} cookie(s) have Secure flag",
        )

    def _is_session_cookie(self, cookie_name: str) -> bool:
        """
        Determine if a cookie is a session cookie based on name patterns.
        Uses Mozilla Observatory's heuristic: cookies with 'login' or 'sess' in the name.
        """
        name_lower = cookie_name.lower()
        return any(pattern in name_lower for pattern in ("login", "sess"))

    def _is_anticsrf_cookie(self, cookie_name: str) -> bool:
        """
        Determine if a cookie is an anti-CSRF token.
        Anti-CSRF tokens need SameSite but should NOT have HttpOnly (JavaScript needs to read them).
        """
        return "csrf" in cookie_name.lower()

    def _check_httponly_flag(self, cookies: list[dict]) -> CheckResult:
        """
        Check if session cookies have HttpOnly flag.
        Only session cookies (auth-related) strictly require HttpOnly.
        Other cookies are checked but don't fail the test.
        """
        session_cookies = [c for c in cookies if self._is_session_cookie(c["name"])]
        other_cookies = [c for c in cookies if not self._is_session_cookie(c["name"])]

        # Session cookies missing HttpOnly is a failure
        session_missing_httponly = [
            c["name"] for c in session_cookies if not c["httponly"]
        ]

        # Other cookies missing HttpOnly is noted but not a failure
        other_missing_httponly = [c["name"] for c in other_cookies if not c["httponly"]]

        if session_missing_httponly:
            return CheckResult(
                name="httponly",
                passed=False,
                message=f"Session cookies missing HttpOnly flag: {', '.join(session_missing_httponly)}",
            )

        # All session cookies have HttpOnly - that's a pass
        if session_cookies and other_missing_httponly:
            # Note other cookies without HttpOnly but don't fail
            return CheckResult(
                name="httponly",
                passed=True,
                message=f"All {len(session_cookies)} session cookie(s) have HttpOnly flag ({len(other_missing_httponly)} non-session cookie(s) missing HttpOnly: {', '.join(other_missing_httponly)})",
            )
        elif session_cookies:
            return CheckResult(
                name="httponly",
                passed=True,
                message=f"All {len(session_cookies)} session cookie(s) have HttpOnly flag",
            )
        elif other_missing_httponly:
            # No session cookies, but other cookies missing HttpOnly
            return CheckResult(
                name="httponly",
                passed=True,
                message=f"No session cookies detected ({len(other_missing_httponly)} non-session cookie(s) missing HttpOnly: {', '.join(other_missing_httponly)})",
            )
        else:
            # All cookies have HttpOnly
            return CheckResult(
                name="httponly",
                passed=True,
                message=f"All {len(cookies)} cookie(s) have HttpOnly flag",
            )

    def _check_samesite_attribute(self, cookies: list[dict]) -> CheckResult:
        """
        Check if cookies have SameSite attribute.
        Anti-CSRF tokens REQUIRE SameSite (failure if missing).
        Other cookies are recommended to have SameSite but it's not required (passes with note).
        """
        anticsrf_cookies = [c for c in cookies if self._is_anticsrf_cookie(c["name"])]
        other_cookies = [c for c in cookies if not self._is_anticsrf_cookie(c["name"])]

        # Anti-CSRF tokens missing SameSite is a failure
        anticsrf_missing_samesite = [
            c["name"] for c in anticsrf_cookies if not c["samesite"]
        ]

        if anticsrf_missing_samesite:
            return CheckResult(
                name="samesite",
                passed=False,
                message=f"Anti-CSRF cookies missing SameSite attribute: {', '.join(anticsrf_missing_samesite)}",
            )

        # Check for problematic SameSite=None without Secure
        problematic = [
            c["name"]
            for c in cookies
            if c["samesite"] and c["samesite"].lower() == "none" and not c["secure"]
        ]

        if problematic:
            return CheckResult(
                name="samesite",
                passed=False,
                message=f"Cookies with SameSite=None must have Secure flag: {', '.join(problematic)}",
            )

        # Check if we have SameSite on all cookies (bonus points, not required)
        other_missing_samesite = [c["name"] for c in other_cookies if not c["samesite"]]

        if not other_missing_samesite:
            # All cookies have SameSite - excellent!
            return CheckResult(
                name="samesite",
                passed=True,
                message=f"All {len(cookies)} cookie(s) have SameSite attribute",
            )
        else:
            # Some cookies missing SameSite - still passes but note it
            return CheckResult(
                name="samesite",
                passed=True,
                message=f"SameSite set on {len(cookies) - len(other_missing_samesite)}/{len(cookies)} cookie(s) (recommended: {', '.join(other_missing_samesite)})",
            )

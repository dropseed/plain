from __future__ import annotations

from typing import TYPE_CHECKING

from ..results import AuditResult, CheckResult
from .base import Audit

if TYPE_CHECKING:
    import requests

    from ..scanner import Scanner


class CSPAudit(Audit):
    """Content Security Policy checks."""

    name = "Content Security Policy (CSP)"
    slug = "csp"
    description = "Validates Content Security Policy configuration to prevent XSS and data injection attacks. Nonce-based policies are recommended. See: https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP"

    def check(self, scanner: Scanner) -> AuditResult:
        """Check if CSP is present and configured securely."""
        response = scanner.fetch()

        # Check for both enforcing and report-only CSP headers
        csp_header = response.headers.get("Content-Security-Policy")
        csp_report_only_header = response.headers.get(
            "Content-Security-Policy-Report-Only"
        )

        if not csp_header and not csp_report_only_header:
            # No CSP header detected at all
            return AuditResult(
                name=self.name,
                detected=False,
                required=self.required,
                checks=[],
                description=self.description,
            )

        # Determine which header to analyze
        # Prefer the enforcing header if both are present
        header_to_analyze = csp_header if csp_header else csp_report_only_header
        is_report_only = csp_header is None and csp_report_only_header is not None

        # Parse CSP once
        directives = self._parse_csp(header_to_analyze)

        # Compute effective CSP (what browsers actually enforce)
        # This removes 'unsafe-inline' when nonces/hashes are present, etc.
        effective_directives = self._get_effective_csp(directives)

        # CSP header detected - run nested checks (based on Google CSP Evaluator)
        checks = [
            self._check_report_only_mode(
                is_report_only, bool(csp_header), bool(csp_report_only_header)
            ),
            self._check_syntax(header_to_analyze, directives),
            self._check_missing_semicolon(header_to_analyze),
            self._check_unsafe_inline(effective_directives, directives),
            self._check_unsafe_eval(directives),
            self._check_plain_url_schemes(directives),
            self._check_wildcards(directives),
            self._check_script_directive(directives),
            self._check_object_src_present(directives),
            self._check_strict_csp_base_uri(directives),
            self._check_strict_csp_object_src(directives),
            self._check_allowlist_bypass(directives),
            self._check_nonce_length(directives),
            self._check_http_source(directives),
            self._check_ip_source(directives),
            self._check_deprecated_directives(directives),
            self._check_reporting(directives, response),
            self._check_strict_dynamic_not_standalone(directives),
        ]

        return AuditResult(
            name=self.name,
            detected=True,
            required=self.required,
            checks=checks,
            description=self.description,
        )

    def _check_report_only_mode(
        self, is_report_only: bool, has_enforcing: bool, has_report_only: bool
    ) -> CheckResult:
        """Check if CSP is in report-only mode (not enforcing)."""
        if is_report_only:
            # Only Report-Only header present - policy is NOT enforced
            return CheckResult(
                name="report-only-mode",
                passed=False,
                message="CSP is in Report-Only mode (violations reported but not enforced; remove '-Report-Only' suffix to enforce)",
            )

        if has_enforcing and has_report_only:
            # Both headers present - likely testing a new policy
            return CheckResult(
                name="report-only-mode",
                passed=True,
                message="CSP has both enforcing and Report-Only headers (testing a new policy alongside existing one)",
            )

        # Only enforcing header present - this is the desired state
        return CheckResult(
            name="report-only-mode",
            passed=True,
            message="CSP is in enforcing mode",
        )

    def _check_unsafe_inline(
        self,
        effective_directives: dict[str, list[str]],
        directives: dict[str, list[str]],
    ) -> CheckResult:
        """Check if CSP contains unsafe-inline in script directives (HIGH severity).

        Uses the effective CSP to avoid false positives when nonces/hashes are present.
        In CSP2+, browsers ignore 'unsafe-inline' when nonces or hashes are present.

        Checks script-src, script-src-elem, and script-src-attr with fallback to default-src.

        Note: We only check script-src, not style-src, because:
        - unsafe-inline in script-src is a critical XSS vulnerability
        - unsafe-inline in style-src is much less dangerous and harder to remove in practice
        """
        # Check all script directives
        directives_to_check = ["script-src", "script-src-attr", "script-src-elem"]

        for directive in directives_to_check:
            # Get the effective directive for this one (handles fallback)
            effective_directive_name = self._get_effective_directive(
                directive, directives
            )

            # Get values from effective CSP (with unsafe-inline removed if nonces/hashes present)
            effective_values = effective_directives.get(effective_directive_name, [])

            if "'unsafe-inline'" in effective_values:
                # Build a message indicating which directive failed
                directive_label = (
                    effective_directive_name
                    if effective_directive_name == directive
                    else f"{directive} (via {effective_directive_name})"
                )
                return CheckResult(
                    name="unsafe-inline",
                    passed=False,
                    message=f"CSP contains 'unsafe-inline' in {directive_label} which allows inline scripts and event handlers",
                )

        return CheckResult(
            name="unsafe-inline",
            passed=True,
            message="CSP does not contain 'unsafe-inline' in script directives",
        )

    def _check_unsafe_eval(self, directives: dict[str, list[str]]) -> CheckResult:
        """Check if CSP contains unsafe-eval directive (MEDIUM severity).

        Checks script-src, script-src-elem, and script-src-attr with fallback to default-src.
        """
        # Check all script directives
        directives_to_check = ["script-src", "script-src-attr", "script-src-elem"]

        for directive in directives_to_check:
            # Get the effective directive for this one (handles fallback)
            effective_directive_name = self._get_effective_directive(
                directive, directives
            )

            # Get values from the directive
            values = directives.get(effective_directive_name, [])

            if "'unsafe-eval'" in values:
                # Build a message indicating which directive failed
                directive_label = (
                    effective_directive_name
                    if effective_directive_name == directive
                    else f"{directive} (via {effective_directive_name})"
                )
                return CheckResult(
                    name="unsafe-eval",
                    passed=False,
                    message=f"CSP contains 'unsafe-eval' in {directive_label} which allows dangerous eval() calls",
                )

        return CheckResult(
            name="unsafe-eval",
            passed=True,
            message="CSP does not contain 'unsafe-eval' in script directives",
        )

    def _check_plain_url_schemes(self, directives: dict[str, list[str]]) -> CheckResult:
        """Check for plain URL schemes like https:, http:, data: (HIGH severity).

        Checks all XSS-critical directives: script-src, script-src-elem, script-src-attr,
        object-src, and base-uri.
        """
        # XSS-critical directives to check
        xss_directives = [
            "script-src",
            "script-src-attr",
            "script-src-elem",
            "object-src",
            "base-uri",
        ]

        dangerous_schemes = ["https:", "http:", "data:"]
        found_issues = []

        for directive in xss_directives:
            # Get the effective directive (handles fallback)
            effective_directive_name = self._get_effective_directive(
                directive, directives
            )

            # Get values from the directive
            values = directives.get(effective_directive_name, [])

            # Check for dangerous schemes
            for scheme in dangerous_schemes:
                if scheme in values:
                    directive_label = (
                        effective_directive_name
                        if effective_directive_name == directive
                        else f"{directive} (via {effective_directive_name})"
                    )
                    found_issues.append(f"{scheme} in {directive_label}")

        if found_issues:
            return CheckResult(
                name="plain-url-schemes",
                passed=False,
                message=f"CSP contains overly broad URL schemes: {', '.join(found_issues)}",
            )

        return CheckResult(
            name="plain-url-schemes",
            passed=True,
            message="CSP does not contain plain URL schemes in XSS-critical directives",
        )

    def _check_wildcards(self, directives: dict[str, list[str]]) -> CheckResult:
        """Check for wildcard (*) in sensitive directives (HIGH severity).

        Checks all XSS-critical directives: script-src, script-src-elem, script-src-attr,
        object-src, and base-uri.
        """
        # XSS-critical directives to check
        xss_directives = [
            "script-src",
            "script-src-attr",
            "script-src-elem",
            "object-src",
            "base-uri",
        ]

        found_wildcards = []

        for directive in xss_directives:
            # Get the effective directive (handles fallback)
            effective_directive_name = self._get_effective_directive(
                directive, directives
            )

            # Get values from the directive
            values = directives.get(effective_directive_name, [])

            # Check for wildcard (*)
            if "*" in values:
                directive_label = (
                    effective_directive_name
                    if effective_directive_name == directive
                    else f"{directive} (via {effective_directive_name})"
                )
                found_wildcards.append(directive_label)

        if found_wildcards:
            return CheckResult(
                name="wildcards",
                passed=False,
                message=f"CSP contains wildcards in: {', '.join(found_wildcards)}",
            )

        return CheckResult(
            name="wildcards",
            passed=True,
            message="CSP does not contain dangerous wildcards in XSS-critical directives",
        )

    def _check_script_directive(self, directives: dict[str, list[str]]) -> CheckResult:
        """Check that script-src or default-src is present."""
        if "script-src" not in directives and "default-src" not in directives:
            return CheckResult(
                name="script-directive",
                passed=False,
                message="CSP missing script-src and default-src (no script restrictions)",
            )

        return CheckResult(
            name="script-directive",
            passed=True,
            message="CSP has script-src or default-src",
        )

    def _check_object_src_present(
        self, directives: dict[str, list[str]]
    ) -> CheckResult:
        """Check that object-src or default-src is present."""
        if "object-src" not in directives and "default-src" not in directives:
            return CheckResult(
                name="object-src-present",
                passed=False,
                message="CSP missing object-src (allows <object>/<embed> injection)",
            )

        return CheckResult(
            name="object-src-present",
            passed=True,
            message="CSP has object-src or default-src",
        )

    def _check_strict_csp_base_uri(
        self, directives: dict[str, list[str]]
    ) -> CheckResult:
        """Check that base-uri is properly configured for strict CSP.

        base-uri is only required when:
        - Script nonces are present, OR
        - Script hashes AND strict-dynamic are present

        Accepts both 'none' and 'self' as valid values.
        """
        # Check script-src (or fallback to default-src) for nonces/hashes
        script_src_directive = self._get_effective_directive("script-src", directives)
        script_values = directives.get(script_src_directive, [])

        # Check for script nonces
        has_script_nonces = any(v.startswith("'nonce-") for v in script_values)

        # Check for script hashes with strict-dynamic
        has_script_hashes = any(v.startswith("'sha") for v in script_values)
        has_strict_dynamic = "'strict-dynamic'" in script_values

        # Only require base-uri when using script nonces or (hashes + strict-dynamic)
        needs_base_uri = has_script_nonces or (has_script_hashes and has_strict_dynamic)

        if not needs_base_uri:
            return CheckResult(
                name="strict-csp-base-uri",
                passed=True,
                message="Not using strict CSP (script nonces/hashes with strict-dynamic) - base-uri check not applicable",
            )

        # Strict CSP detected - base-uri should be present
        if "base-uri" not in directives:
            return CheckResult(
                name="strict-csp-base-uri",
                passed=False,
                message="Strict CSP missing base-uri (can be 'none' or 'self' to prevent base tag injection)",
            )

        # Check if base-uri is 'none' or 'self'
        base_uri_values = directives.get("base-uri", [])
        if base_uri_values == ["'none'"] or base_uri_values == ["'self'"]:
            value_label = base_uri_values[0]
            return CheckResult(
                name="strict-csp-base-uri",
                passed=True,
                message=f"Strict CSP base-uri correctly set to {value_label}",
            )

        # base-uri has other values
        return CheckResult(
            name="strict-csp-base-uri",
            passed=False,
            message=f"Strict CSP base-uri should be 'none' or 'self' (currently: {' '.join(base_uri_values)})",
        )

    def _check_strict_csp_object_src(
        self, directives: dict[str, list[str]]
    ) -> CheckResult:
        """Check that object-src is defined for strict CSP.

        For strict CSPs, object-src should be defined. Setting it to 'none' is
        recommended but not required - the policy may intentionally allow some
        object embeds.
        """
        has_nonces_or_hashes = any(
            any(v.startswith("'nonce-") or v.startswith("'sha") for v in values)
            for values in directives.values()
        )

        if not has_nonces_or_hashes:
            return CheckResult(
                name="strict-csp-object-src",
                passed=True,
                message="Not using strict CSP (nonces/hashes) - object-src check not applicable",
            )

        # Strict CSP detected - object-src should be defined
        object_src = directives.get("object-src", [])
        default_src = directives.get("default-src", [])

        # Check if object-src is defined (either directly or via default-src)
        if not object_src and not default_src:
            return CheckResult(
                name="strict-csp-object-src",
                passed=False,
                message="Strict CSP missing object-src (allows plugin injection; set to 'none' if not using plugins)",
            )

        # If object-src is defined, check if it's 'none' (best practice)
        if object_src == ["'none'"]:
            return CheckResult(
                name="strict-csp-object-src",
                passed=True,
                message="Strict CSP object-src correctly set to 'none'",
            )

        # object-src is defined but not 'none'
        if object_src:
            return CheckResult(
                name="strict-csp-object-src",
                passed=True,
                message=f"Strict CSP has object-src defined (consider tightening to 'none': currently {' '.join(object_src)})",
            )

        # Covered by default-src
        return CheckResult(
            name="strict-csp-object-src",
            passed=True,
            message="Strict CSP object-src covered by default-src (consider explicit object-src 'none')",
        )

    def _check_allowlist_bypass(self, directives: dict[str, list[str]]) -> CheckResult:
        """Check for known CSP bypass domains in allowlists (HIGH severity)."""
        # Top known bypass domains from Google CSP Evaluator
        # (subset of most dangerous JSONP/Angular endpoints)
        bypass_domains = {
            # Google services with JSONP endpoints
            "google-analytics.com",
            "www.google-analytics.com",
            "ssl.google-analytics.com",
            "googletagmanager.com",
            "www.googletagmanager.com",
            "www.googleadservices.com",
            # CDNs with Angular/JSONP
            "ajax.googleapis.com",
            "cdnjs.cloudflare.com",
            "cdn.jsdelivr.net",
            # Yandex
            "yandex.st",
            "yastatic.net",
        }

        script_src = directives.get("script-src", [])
        default_src = directives.get("default-src", [])
        effective_src = script_src if script_src else default_src

        found_bypasses = []
        for value in effective_src:
            # Remove protocol and quotes
            cleaned = (
                value.replace("https://", "").replace("http://", "").replace("'", "")
            )
            # Check if any bypass domain is in this value
            for bypass_domain in bypass_domains:
                if bypass_domain in cleaned:
                    found_bypasses.append(bypass_domain)
                    break

        if found_bypasses:
            return CheckResult(
                name="allowlist-bypass",
                passed=False,
                message=f"CSP allows known bypass domains: {', '.join(set(found_bypasses))}",
            )

        return CheckResult(
            name="allowlist-bypass",
            passed=True,
            message="CSP does not contain known bypass domains",
        )

    def _check_nonce_length(self, directives: dict[str, list[str]]) -> CheckResult:
        """Check that nonces are at least 8 characters and use valid base64/base64url charset.

        Follows Google CSP Evaluator: minimum 8 characters (not 22).
        Charset validation is informational only.
        """
        import re

        # Collect all nonces from all directives
        nonces = []
        for values in directives.values():
            for value in values:
                if value.startswith("'nonce-"):
                    # Extract nonce value (remove 'nonce-' prefix and trailing ')
                    nonce = value[7:-1] if value.endswith("'") else value[7:]
                    nonces.append(nonce)

        if not nonces:
            # No nonces used, check passes
            return CheckResult(
                name="nonce-length",
                passed=True,
                message="No nonces in CSP",
            )

        length_issues = []
        charset_warnings = []

        # Check each nonce
        for nonce in nonces:
            # Check length (minimum 8 characters per Google CSP Evaluator)
            if len(nonce) < 8:
                length_issues.append(
                    f"nonce '{nonce}' is too short ({len(nonce)} chars, minimum 8)"
                )

            # Check base64/base64url charset (informational)
            # Standard base64: A-Z, a-z, 0-9, +, /, =
            # URL-safe base64url: A-Z, a-z, 0-9, -, _ (typically no padding)
            if not re.match(r"^[A-Za-z0-9+/=_-]+$", nonce):
                charset_warnings.append(
                    f"nonce '{nonce}' contains non-base64 characters (should use base64/base64url charset)"
                )

        # Length issues are failures
        if length_issues:
            return CheckResult(
                name="nonce-length",
                passed=False,
                message=f"Nonce validation failed: {'; '.join(length_issues)}",
            )

        # Charset warnings are informational
        if charset_warnings:
            return CheckResult(
                name="nonce-length",
                passed=True,
                message=f"Nonces valid but consider using base64 charset: {'; '.join(charset_warnings)}",
            )

        return CheckResult(
            name="nonce-length",
            passed=True,
            message=f"All {len(nonces)} nonce(s) are valid",
        )

    def _check_http_source(self, directives: dict[str, list[str]]) -> CheckResult:
        """Check for http:// URLs in CSP directives (mixed content vulnerability)."""
        http_sources = []

        # Check all directives for http:// URLs
        for directive_name, values in directives.items():
            for value in values:
                # Look for http:// (but not http: scheme which is checked elsewhere)
                if value.startswith("http://") or value.startswith("'http://"):
                    http_sources.append(f"{directive_name}: {value}")

        if http_sources:
            return CheckResult(
                name="http-source",
                passed=False,
                message=f"CSP contains insecure HTTP sources: {', '.join(http_sources)}",
            )

        return CheckResult(
            name="http-source",
            passed=True,
            message="CSP does not contain insecure HTTP sources",
        )

    def _check_syntax(
        self, csp_header: str, directives: dict[str, list[str]]
    ) -> CheckResult:
        """Check for CSP syntax issues: unknown directives, invalid keywords, missing separators."""
        issues = []

        # Known CSP directives (CSP Level 3 and legacy)
        known_directives = {
            # Fetch directives
            "default-src",
            "script-src",
            "script-src-elem",
            "script-src-attr",
            "style-src",
            "style-src-elem",
            "style-src-attr",
            "img-src",
            "font-src",
            "connect-src",
            "media-src",
            "object-src",
            "frame-src",
            "child-src",
            "worker-src",
            "manifest-src",
            "prefetch-src",  # Deprecated but valid
            # Document directives
            "base-uri",
            "plugin-types",  # Deprecated but valid
            "sandbox",
            "disown-opener",  # Deprecated but valid
            # Navigation directives
            "form-action",
            "frame-ancestors",
            "navigate-to",
            # Reporting directives
            "report-uri",  # Still needed for Firefox/Safari
            "report-to",
            # Other directives
            "upgrade-insecure-requests",
            "block-all-mixed-content",  # Deprecated
            "reflected-xss",  # Deprecated but valid
            "referrer",  # Deprecated but valid
            "require-sri-for",  # Deprecated but valid
            "require-trusted-types-for",
            "trusted-types",
            "webrtc",
        }

        # Known CSP keywords (must be in quotes)
        known_keywords = {
            "'none'",
            "'self'",
            "'unsafe-inline'",
            "'unsafe-eval'",
            "'unsafe-hashes'",
            "'strict-dynamic'",
            "'report-sample'",
            "'wasm-unsafe-eval'",
        }

        # Check for unknown directives (typos)
        for directive_name in directives.keys():
            if directive_name not in known_directives:
                # Could be a typo or experimental directive
                issues.append(f"unknown directive '{directive_name}' (typo?)")

        # Check for invalid keywords (missing quotes or typos)
        for directive_name, values in directives.items():
            for value in values:
                # Keywords without quotes (common mistake)
                if value.lower() in [
                    "none",
                    "self",
                    "unsafe-inline",
                    "unsafe-eval",
                    "strict-dynamic",
                ]:
                    issues.append(
                        f"{directive_name} has unquoted keyword '{value}' (should be '{value}')"
                    )
                # Quoted but not a recognized keyword (possible typo)
                elif value.startswith("'") and value.endswith("'"):
                    if (
                        value not in known_keywords
                        and not value.startswith("'nonce-")
                        and not value.startswith("'sha")
                    ):
                        issues.append(
                            f"{directive_name} has unrecognized keyword {value} (typo?)"
                        )

        if issues:
            return CheckResult(
                name="syntax",
                passed=False,
                message=f"CSP syntax issues: {'; '.join(issues[:3])}",  # Limit to 3 issues
            )

        return CheckResult(
            name="syntax",
            passed=True,
            message="CSP syntax is valid",
        )

    def _check_ip_source(self, directives: dict[str, list[str]]) -> CheckResult:
        """Check for IP address sources in CSP (less secure than domains)."""
        import ipaddress

        ip_sources = []

        # Check all directives for IP addresses
        for directive_name, values in directives.items():
            for value in values:
                # Skip keywords
                if value.startswith("'"):
                    continue

                # Remove port if present
                host = value.split(":")[0]

                # Try to parse as IP address
                try:
                    ipaddress.ip_address(host)
                    ip_sources.append(f"{directive_name}: {value}")
                except ValueError:
                    # Not an IP address, that's good
                    continue

        if ip_sources:
            return CheckResult(
                name="ip-source",
                passed=False,
                message=f"CSP uses IP addresses (prefer domains): {', '.join(ip_sources)}",
            )

        return CheckResult(
            name="ip-source",
            passed=True,
            message="CSP does not use IP address sources",
        )

    def _check_deprecated_directives(
        self, directives: dict[str, list[str]]
    ) -> CheckResult:
        """Check for deprecated CSP directives (matches Google CSP Evaluator)."""
        deprecated = {
            "reflected-xss": "use X-XSS-Protection header instead",
            "referrer": "use Referrer-Policy header instead",
            "disown-opener": "use Cross Origin Opener Policy header instead",
            "prefetch-src": "may cease to work at any time",
        }

        found_deprecated = []

        for directive_name in directives.keys():
            if directive_name in deprecated:
                reason = deprecated[directive_name]
                found_deprecated.append(f"{directive_name} ({reason})")

        if found_deprecated:
            return CheckResult(
                name="deprecated-directives",
                passed=False,
                message=f"CSP uses deprecated directives: {'; '.join(found_deprecated)}",
            )

        return CheckResult(
            name="deprecated-directives",
            passed=True,
            message="CSP does not use deprecated directives",
        )

    def _check_missing_semicolon(self, csp_header: str) -> CheckResult:
        """Check for missing semicolons between directives (SYNTAX severity)."""
        # Known CSP directive names
        known_directives = {
            "default-src",
            "script-src",
            "script-src-elem",
            "script-src-attr",
            "style-src",
            "style-src-elem",
            "style-src-attr",
            "img-src",
            "font-src",
            "connect-src",
            "media-src",
            "object-src",
            "frame-src",
            "child-src",
            "worker-src",
            "manifest-src",
            "base-uri",
            "form-action",
            "frame-ancestors",
            "navigate-to",
            "report-uri",
            "report-to",
            "sandbox",
            "upgrade-insecure-requests",
            "block-all-mixed-content",
            "require-trusted-types-for",
            "trusted-types",
            "webrtc",
        }

        # Split by semicolon and check each directive part
        parts = csp_header.split(";")
        for part in parts:
            tokens = part.strip().split()
            if not tokens:
                continue

            # Check if any known directive appears after the first token
            # This indicates a missing semicolon
            for i, token in enumerate(tokens[1:], 1):
                if token in known_directives:
                    return CheckResult(
                        name="missing-semicolon",
                        passed=False,
                        message=f"Missing semicolon before '{token}' directive",
                    )

        return CheckResult(
            name="missing-semicolon",
            passed=True,
            message="CSP directives properly separated with semicolons",
        )

    def _check_reporting(
        self, directives: dict[str, list[str]], response: requests.Response
    ) -> CheckResult:
        """Check if CSP reporting is configured with modern Reporting-Endpoints header.

        Validates that report-to endpoints exist in Reporting-Endpoints header.
        The report-uri directive and Report-To header are deprecated and should not be used.
        """
        has_report_uri = "report-uri" in directives
        has_report_to = "report-to" in directives

        # Check for Reporting-Endpoints header (modern, Reporting API v1)
        reporting_endpoints_header = response.headers.get("Reporting-Endpoints", "")

        # No reporting configured - this is optional
        if not has_report_uri and not has_report_to:
            return CheckResult(
                name="reporting",
                passed=True,
                message="CSP has no reporting configured (optional)",
            )

        # Using deprecated report-uri directive
        if has_report_uri:
            return CheckResult(
                name="reporting",
                passed=False,
                message="CSP uses deprecated report-uri (migrate to report-to with Reporting-Endpoints)",
            )

        # Using report-to directive - validate the endpoint exists in Reporting-Endpoints
        if has_report_to:
            # Get the endpoint name(s) from the directive
            report_to_values = directives.get("report-to", [])
            if not report_to_values:
                return CheckResult(
                    name="reporting",
                    passed=False,
                    message="CSP report-to directive is empty",
                )

            endpoint_name = report_to_values[0]  # report-to should have one value

            # Must have Reporting-Endpoints header for report-to to work
            if not reporting_endpoints_header:
                return CheckResult(
                    name="reporting",
                    passed=False,
                    message="CSP report-to directive requires Reporting-Endpoints header",
                )

            # Validate endpoint exists in Reporting-Endpoints header
            # Format: endpoint-name="url", other="url2"
            if f'{endpoint_name}="' in reporting_endpoints_header:
                return CheckResult(
                    name="reporting",
                    passed=True,
                    message="CSP reporting correctly configured with Reporting-Endpoints",
                )
            else:
                return CheckResult(
                    name="reporting",
                    passed=False,
                    message=f"CSP report-to references '{endpoint_name}' but it's not defined in Reporting-Endpoints header",
                )

        # Shouldn't reach here, but safety fallback
        return CheckResult(
            name="reporting",
            passed=True,
            message="CSP reporting check completed",
        )

    def _check_strict_dynamic_not_standalone(
        self, directives: dict[str, list[str]]
    ) -> CheckResult:
        """Check that 'strict-dynamic' is not used without nonces/hashes (INFO severity)."""
        script_src = directives.get("script-src", directives.get("default-src", []))

        # Check if strict-dynamic is present
        has_strict_dynamic = "'strict-dynamic'" in script_src

        if not has_strict_dynamic:
            # Not using strict-dynamic, check not applicable
            return CheckResult(
                name="strict-dynamic-standalone",
                passed=True,
                message="CSP does not use 'strict-dynamic'",
            )

        # Check if using nonces or hashes
        has_nonces = any(val.startswith("'nonce-") for val in script_src)
        has_hashes = any(val.startswith("'sha") for val in script_src)

        if not has_nonces and not has_hashes:
            return CheckResult(
                name="strict-dynamic-standalone",
                passed=False,
                message="CSP uses 'strict-dynamic' without nonces/hashes (will block ALL scripts)",
            )

        return CheckResult(
            name="strict-dynamic-standalone",
            passed=True,
            message="CSP uses 'strict-dynamic' with nonces/hashes",
        )

    def _parse_csp(self, csp_header: str) -> dict[str, list[str]]:
        """Parse CSP header into a dictionary of directives."""
        directives = {}
        for directive in csp_header.split(";"):
            directive = directive.strip()
            if not directive:
                continue

            parts = directive.split()
            if not parts:
                continue

            directive_name = parts[0]
            directive_values = parts[1:] if len(parts) > 1 else []
            directives[directive_name] = directive_values

        return directives

    def _get_effective_directive(
        self, directive: str, directives: dict[str, list[str]]
    ) -> str:
        """Get the effective directive considering fallback rules.

        Returns the directive itself if present, or the appropriate fallback directive.
        Follows CSP spec fallback rules:
        - script-src-elem/attr → script-src → default-src
        - style-src-elem/attr → style-src → default-src
        - Other fetch directives → default-src
        """
        if directive in directives:
            return directive

        # Handle script-src-elem and script-src-attr fallback
        if directive in ("script-src-attr", "script-src-elem"):
            if "script-src" in directives:
                return "script-src"

        # Handle style-src-elem and style-src-attr fallback
        if directive in ("style-src-attr", "style-src-elem"):
            if "style-src" in directives:
                return "style-src"

        # Fetch directives fall back to default-src
        fetch_directives = {
            "child-src",
            "connect-src",
            "font-src",
            "frame-src",
            "img-src",
            "manifest-src",
            "media-src",
            "object-src",
            "script-src",
            "script-src-attr",
            "script-src-elem",
            "style-src",
            "style-src-attr",
            "style-src-elem",
            "worker-src",
            "prefetch-src",
        }

        if directive in fetch_directives:
            return "default-src"

        return directive

    def _get_effective_csp(
        self, directives: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        """Compute the effective CSP as enforced by browsers (CSP2+).

        Browsers ignore certain directive values in the presence of nonces/hashes:
        - 'unsafe-inline' is ignored if nonces or hashes are present (CSP2+)
        - Allowlist sources are ignored when 'strict-dynamic' is present (CSP3+)

        This prevents false positives on strict nonce-based CSPs.
        """
        # Create a deep copy of directives
        effective_directives: dict[str, list[str]] = {}
        for directive, values in directives.items():
            effective_directives[directive] = list(values)

        # Check script-src, script-src-attr, and script-src-elem
        for directive_to_check in ["script-src", "script-src-attr", "script-src-elem"]:
            # Get the effective directive for this one (handles fallback)
            effective_directive_name = self._get_effective_directive(
                directive_to_check, directives
            )

            # Skip if not in effective directives
            if effective_directive_name not in effective_directives:
                continue

            values = directives.get(effective_directive_name, [])
            effective_values = effective_directives[effective_directive_name]

            # Check if nonces or hashes are present
            has_nonces = any(v.startswith("'nonce-") for v in values)
            has_hashes = any(v.startswith("'sha") for v in values)

            if has_nonces or has_hashes:
                # CSP2+: Remove 'unsafe-inline' when nonces/hashes are present
                if "'unsafe-inline'" in effective_values:
                    effective_values.remove("'unsafe-inline'")

            # Check if strict-dynamic is present
            has_strict_dynamic = "'strict-dynamic'" in values

            if has_strict_dynamic:
                # CSP3+: Remove allowlist sources when strict-dynamic is present
                # Keep only keywords (starting with ') except 'self' and 'unsafe-inline'
                effective_values[:] = [
                    v
                    for v in effective_values
                    if v.startswith("'")
                    and v not in ("'self'", "'unsafe-inline'")
                    or v in ("'strict-dynamic'",)  # Keep strict-dynamic itself
                ]

        return effective_directives

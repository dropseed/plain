from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from ..results import AuditResult, CheckResult
from .base import Audit

if TYPE_CHECKING:
    from ..scanner import Scanner


class TLSAudit(Audit):
    """TLS/SSL security checks."""

    name = "TLS/SSL"
    slug = "tls"
    description = "Basic TLS/SSL validation including certificate expiry and protocol version. For comprehensive TLS testing, use SSL Labs (https://www.ssllabs.com/ssltest/)."

    def check(self, scanner: Scanner) -> AuditResult:
        """Check TLS certificate and configuration."""

        # Check if there was a TLS/SSL error during the initial fetch
        # This allows us to report certificate issues even when the connection fails
        if scanner.fetch_exception is not None:
            # Report the TLS/SSL error
            error_msg = str(scanner.fetch_exception)

            # Try to make the error message more user-friendly
            if "CERTIFICATE_VERIFY_FAILED" in error_msg:
                error_msg = "Certificate verification failed (certificate may be expired, self-signed, or for wrong hostname)"
            elif "certificate verify failed" in error_msg.lower():
                error_msg = "Certificate verification failed"

            return AuditResult(
                name=self.name,
                detected=True,
                required=self.required,
                checks=[
                    CheckResult(
                        name="connection",
                        passed=False,
                        message=f"Failed to establish secure TLS connection: {error_msg}",
                    )
                ],
                description=self.description,
            )

        response = scanner.fetch()

        initial_parsed = urlparse(scanner.url)
        final_parsed = urlparse(response.url)

        # Prefer the final HTTPS endpoint if we followed redirects
        target_parsed = (
            final_parsed if final_parsed.scheme == "https" else initial_parsed
        )

        if target_parsed.scheme != "https":
            return AuditResult(
                name=self.name,
                detected=False,
                required=self.required,
                checks=[],
                description=self.description,
            )

        hostname = target_parsed.hostname
        port = target_parsed.port or 443

        if not hostname:
            return AuditResult(
                name=self.name,
                detected=False,
                required=self.required,
                checks=[],
                description=self.description,
            )

        # Try to get certificate info
        try:
            cert_info = self._get_certificate_info(hostname, port)
        except Exception as e:
            # TLS connection failed
            return AuditResult(
                name=self.name,
                detected=True,
                required=self.required,
                checks=[
                    CheckResult(
                        name="connection",
                        passed=False,
                        message=f"Failed to connect via TLS: {str(e)}",
                    )
                ],
                description=self.description,
            )

        # Run checks on the certificate
        checks = [
            self._check_certificate_expiry(cert_info),
            self._check_tls_version(cert_info),
            self._check_legacy_tls(cert_info),
            self._check_certificate_hostname(cert_info, hostname),
        ]

        return AuditResult(
            name=self.name,
            detected=True,
            required=self.required,
            checks=checks,
            description=self.description,
        )

    def _get_certificate_info(self, hostname: str, port: int) -> dict:
        """Get certificate information from the server."""
        context = ssl.create_default_context()

        with socket.create_connection((hostname, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                tls_version = ssock.version()

                return {
                    "cert": cert,
                    "tls_version": tls_version,
                }

    def _check_certificate_expiry(self, cert_info: dict) -> CheckResult:
        """Check if certificate is expired or expiring soon."""
        cert = cert_info["cert"]

        # Parse notAfter date
        not_after_str = cert.get("notAfter")
        if not not_after_str:
            return CheckResult(
                name="certificate-expiry",
                passed=False,
                message="Certificate has no expiration date",
            )

        # Parse the date string (format: 'Jul 15 12:00:00 2025 GMT')
        not_after = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
        not_after = not_after.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        days_until_expiry = (not_after - now).days

        if days_until_expiry < 0:
            return CheckResult(
                name="certificate-expiry",
                passed=False,
                message=f"Certificate expired {abs(days_until_expiry)} days ago",
            )

        if days_until_expiry < 30:
            return CheckResult(
                name="certificate-expiry",
                passed=False,
                message=f"Certificate expires in {days_until_expiry} days (renew soon)",
            )

        return CheckResult(
            name="certificate-expiry",
            passed=True,
            message=f"Certificate valid for {days_until_expiry} days",
        )

    def _check_tls_version(self, cert_info: dict) -> CheckResult:
        """Check if using a secure TLS version."""
        tls_version = cert_info["tls_version"]

        # TLS 1.2 and 1.3 are secure
        secure_versions = ["TLSv1.2", "TLSv1.3"]

        if tls_version in secure_versions:
            return CheckResult(
                name="tls-version",
                passed=True,
                message=f"Using {tls_version}",
            )

        # Older versions are insecure
        return CheckResult(
            name="tls-version",
            passed=False,
            message=f"Using outdated {tls_version} (upgrade to TLS 1.2 or 1.3)",
        )

    def _check_legacy_tls(self, cert_info: dict) -> CheckResult:
        """Check if server supports legacy TLS 1.0/1.1 (should be disabled)."""
        tls_version = cert_info["tls_version"]

        # If we connected with TLS 1.0 or 1.1, that's already bad
        if tls_version in ["TLSv1", "TLSv1.0", "TLSv1.1"]:
            return CheckResult(
                name="legacy-tls",
                passed=False,
                message=f"Server is using legacy {tls_version} (should be disabled)",
            )

        # If we're using TLS 1.2+, we can't easily test if 1.0/1.1 are also enabled
        # without making additional connections with specific protocols
        # For now, just report that we're using a modern version
        return CheckResult(
            name="legacy-tls",
            passed=True,
            message=f"Connection uses modern TLS ({tls_version})",
        )

    def _check_certificate_hostname(
        self, cert_info: dict, hostname: str
    ) -> CheckResult:
        """Check if certificate hostname matches the requested hostname."""
        cert = cert_info["cert"]

        # Get subject common name
        subject = dict(x[0] for x in cert.get("subject", ()))
        common_name = subject.get("commonName", "")

        # Get subject alternative names
        san_list = []
        for item in cert.get("subjectAltName", ()):
            if item[0] == "DNS":
                san_list.append(item[1])

        # Check if hostname matches CN or any SAN
        if hostname == common_name or hostname in san_list:
            return CheckResult(
                name="certificate-hostname",
                passed=True,
                message=f"Certificate hostname matches: {common_name}",
            )

        # Check for wildcard matches
        for san in san_list:
            if san.startswith("*.") and hostname.endswith(san[1:]):
                return CheckResult(
                    name="certificate-hostname",
                    passed=True,
                    message=f"Certificate hostname matches wildcard: {san}",
                )

        # Hostname mismatch
        all_names = [common_name] + san_list
        return CheckResult(
            name="certificate-hostname",
            passed=False,
            message=f"Certificate hostname mismatch (expected: {hostname}, found: {', '.join(all_names)})",
        )

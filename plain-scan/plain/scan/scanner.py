from __future__ import annotations

from typing import TYPE_CHECKING

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError

from . import __version__
from .audits import (
    ContentTypeOptionsAudit,
    CookiesAudit,
    CORSAudit,
    CSPAudit,
    FrameOptionsAudit,
    HSTSAudit,
    RedirectsAudit,
    ReferrerPolicyAudit,
    StatusCodeAudit,
    TLSAudit,
)
from .metadata import ScanMetadata

if TYPE_CHECKING:
    from .audits.base import Audit
    from .results import ScanResult


class Scanner:
    """Main scanner that runs security checks against a URL."""

    def __init__(self, url: str, disabled_audits: set[str] | None = None) -> None:
        self.url = url
        self.disabled_audits = disabled_audits or set()
        self.response: requests.Response | None = None
        self.fetch_exception: Exception | None = None

        # Initialize all available audits
        # Required audits first, then optional ones
        self.audits: list[Audit] = [
            # Required security audits
            StatusCodeAudit(),  # Check status code first (most fundamental)
            CSPAudit(),
            HSTSAudit(),
            TLSAudit(),
            RedirectsAudit(),
            ContentTypeOptionsAudit(),
            FrameOptionsAudit(),
            ReferrerPolicyAudit(),
            # Optional audits
            CookiesAudit(),
            CORSAudit(),
        ]

    def fetch(self) -> requests.Response:
        """Fetch the URL and cache the response."""
        if self.response is None:
            try:
                user_agent = (
                    f"plain-scan/{__version__} (+https://plainframework.com/scan)"
                )
                self.response = requests.get(
                    self.url,
                    allow_redirects=True,
                    timeout=30,
                    headers={"User-Agent": user_agent},
                )
            except (
                SSLError,
                RequestsConnectionError,
            ) as e:
                # Store TLS/network exceptions so TLSAudit can report them
                self.fetch_exception = e
                raise
        return self.response

    def scan(self) -> ScanResult:
        """Run all security checks and return results."""
        from .results import ScanResult

        # Try to fetch the URL once
        # If this fails with TLS/network errors, we store the exception
        # and continue so TLSAudit can report the issue
        response = None
        try:
            response = self.fetch()
        except (
            SSLError,
            RequestsConnectionError,
        ):
            # Exception is already stored in self.fetch_exception
            # Continue with scan so TLSAudit can report it
            pass

        # Collect metadata about the request
        metadata = ScanMetadata.from_response(response)

        # Run each audit
        scan_result = ScanResult(url=self.url, metadata=metadata)
        for audit in self.audits:
            # If audit is disabled by user, add to results but mark as disabled
            if audit.slug in self.disabled_audits:
                from .results import AuditResult

                scan_result.audits.append(
                    AuditResult(
                        name=audit.name,
                        detected=False,
                        required=audit.required,
                        checks=[],
                        disabled=True,
                        description=audit.description,
                    )
                )
            else:
                # Try to run the audit
                # If the initial fetch failed and this audit needs the response,
                # it will fail. TLSAudit handles fetch exceptions specially.
                try:
                    audit_result = audit.check(self)
                    scan_result.audits.append(audit_result)
                except (
                    SSLError,
                    RequestsConnectionError,
                ):
                    # Audit couldn't run due to fetch failure
                    # Skip non-TLS audits since they need a successful response
                    if audit.slug != "tls":
                        from .results import AuditResult, CheckResult

                        scan_result.audits.append(
                            AuditResult(
                                name=audit.name,
                                detected=False,
                                required=audit.required,
                                checks=[
                                    CheckResult(
                                        name="Connection",
                                        passed=False,
                                        message="Could not connect to URL to run audit",
                                    )
                                ],
                                description=audit.description,
                            )
                        )
                    else:
                        # TLS audit should have handled this - re-raise
                        raise

        return scan_result

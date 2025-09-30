from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from plain.logs.utils import log_response
from plain.runtime import settings

from .views import CsrfFailureView

if TYPE_CHECKING:
    from plain.http import Response
    from plain.http.request import Request

logger = logging.getLogger("plain.security.csrf")


class CsrfViewMiddleware:
    """
    Modern CSRF protection middleware using Sec-Fetch-Site headers and origin validation.
    Based on Filippo Valsorda's 2025 research (https://words.filippo.io/csrf/).

    Note: This provides same-origin (not same-site) protection. Same-site origins
    like subdomains can have different trust levels and are rejected.
    """

    def __init__(self, get_response: Callable[[Request], Response]):
        self.get_response = get_response

        # Compile CSRF exempt patterns once for performance
        self.csrf_exempt_patterns: list[re.Pattern[str]] = [
            re.compile(r) for r in settings.CSRF_EXEMPT_PATHS
        ]

    def __call__(self, request: Request) -> Response:
        allowed, reason = self.should_allow_request(request)

        if allowed:
            return self.get_response(request)
        else:
            return self.reject(request, reason)

    def should_allow_request(self, request: Request) -> tuple[bool, str]:
        # 1. Allow safe methods (GET, HEAD, OPTIONS)
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True, f"Safe HTTP method: {request.method}"

        # 2. Path-based exemption (regex patterns)
        for pattern in self.csrf_exempt_patterns:
            if pattern.search(request.path_info):
                return (
                    True,
                    f"Path {request.path_info} matches exempt pattern {pattern.pattern}",
                )

        origin = request.headers.get("Origin")
        sec_fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()

        # 3. Check trusted origins allow-list

        if origin and origin in settings.CSRF_TRUSTED_ORIGINS:
            return True, f"Trusted origin: {origin}"

        # 4. Primary protection: Check Sec-Fetch-Site header
        if sec_fetch_site in ("same-origin", "none"):
            return (
                True,
                f"Same-origin request from Sec-Fetch-Site: {sec_fetch_site}",
            )
        elif sec_fetch_site in ("cross-site", "same-site"):
            return (
                False,
                f"Cross-origin request detected from Sec-Fetch-Site: {sec_fetch_site}",
            )

        # 5. No fetch metadata or Origin headers - allow (non-browser requests)
        if not origin and not sec_fetch_site:
            return (
                True,
                "No Origin or Sec-Fetch-Site header - likely non-browser or old browser",
            )

        # 6. Fallback: Origin vs Host comparison for older browsers
        # Note: On pre-2023 browsers, HTTP→HTTPS transitions may cause mismatches
        # (Origin shows :443, request sees :80 if TLS terminated upstream).
        # HSTS helps here; otherwise add external origins to CSRF_TRUSTED_ORIGINS.
        if origin == "null":
            return False, "Cross-origin request detected - null Origin header"

        if (parsed_origin := urlparse(origin)) and (host := request.host):
            try:
                # Scheme-agnostic host:port comparison
                origin_host = parsed_origin.hostname
                origin_port = parsed_origin.port or (
                    80
                    if parsed_origin.scheme == "http"
                    else 443
                    if parsed_origin.scheme == "https"
                    else None
                )

                # Extract hostname from request host (similar to how we parse origin)
                # Use a fake scheme since we only care about host parsing
                parsed_host = urlparse(f"http://{host}")
                request_host = parsed_host.hostname or host
                request_port = request.port

                # Compare hostname and port (scheme-agnostic)
                # Both origin_host and request_host are normalized by urlparse (IPv6 brackets stripped)
                if origin_host and origin_port and request_host and request_port:
                    if (
                        origin_host.lower() == request_host.lower()
                        and origin_port == int(request_port)
                    ):
                        return (
                            True,
                            f"Same-origin request - Origin {origin} matches Host {host}",
                        )
            except ValueError:
                pass

        # Origin present but doesn't match host
        return (
            False,
            f"Cross-origin request detected - Origin {origin} does not match Host",
        )

    def reject(self, request: Request, reason: str) -> Response:
        """Reject a request with a 403 Forbidden response."""

        response = CsrfFailureView.as_view()(request, reason=reason)
        log_response(
            "Forbidden (%s): %s",
            reason,
            request.path,
            response=response,
            request=request,
            logger=logger,
        )
        return response

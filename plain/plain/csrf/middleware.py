import re
from typing import TYPE_CHECKING

from plain.http import HttpMiddleware, SuspiciousOperationError400
from plain.runtime import settings

from .origin import check_cross_origin

if TYPE_CHECKING:
    from plain.http import Request, Response


class CsrfViewMiddleware(HttpMiddleware):
    """
    Modern CSRF protection middleware using Sec-Fetch-Site headers and origin validation.
    Based on Filippo Valsorda's 2025 research (https://words.filippo.io/csrf/).

    Note: This provides same-origin (not same-site) protection. Same-site origins
    like subdomains can have different trust levels and are rejected.
    """

    def __init__(self):
        # Compile CSRF exempt patterns once for performance
        self.csrf_exempt_patterns: list[re.Pattern[str]] = [
            re.compile(r) for r in settings.CSRF_EXEMPT_PATHS
        ]

    def before_request(self, request: Request) -> Response | None:
        allowed, reason = self.should_allow_request(request)

        if not allowed:
            raise SuspiciousOperationError400(reason)

        return None

    def should_allow_request(self, request: Request) -> tuple[bool, str]:
        # 1. Allow safe methods (GET, HEAD, OPTIONS)
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True, f"CSRF allowed: Safe HTTP method: {request.method}"

        # 2. Path-based exemption (regex patterns)
        for pattern in self.csrf_exempt_patterns:
            if pattern.search(request.path):
                return (
                    True,
                    f"CSRF allowed: Path {request.path} matches exempt pattern {pattern.pattern}",
                )

        return check_cross_origin(request)

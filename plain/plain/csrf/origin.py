"""The cross-origin decision shared by the CSRF middleware and WebSocket upgrades."""

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from plain.runtime import settings

if TYPE_CHECKING:
    from plain.http import Request


def check_cross_origin(request: Request) -> tuple[bool, str]:
    """Decide whether a browser-originated request is same-origin.

    The cross-origin half of the CSRF rule, shared with the WebSocket
    upgrade path (a websocket handshake is a GET, so the middleware
    lets it through, but session cookies ride along on it exactly as
    they do on a POST). Trusted origins first, then `Sec-Fetch-Site`,
    then allow requests with neither header (non-browser clients),
    then fall back to a scheme-agnostic Origin-vs-Host comparison.
    """
    origin = request.headers.get("Origin")
    sec_fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()

    # Check trusted origins allow-list

    if origin and origin in settings.CSRF_TRUSTED_ORIGINS:
        return True, f"CSRF allowed: Trusted origin: {origin}"

    # Primary protection: Check Sec-Fetch-Site header
    if sec_fetch_site in ("same-origin", "none"):
        return (
            True,
            f"CSRF allowed: Same-origin request from Sec-Fetch-Site: {sec_fetch_site}",
        )
    elif sec_fetch_site in ("cross-site", "same-site"):
        return (
            False,
            f"CSRF rejected: Cross-origin request from Sec-Fetch-Site: {sec_fetch_site}",
        )

    # No fetch metadata or Origin headers - allow (non-browser requests)
    if not origin and not sec_fetch_site:
        return (
            True,
            "CSRF allowed: No Origin or Sec-Fetch-Site header - likely non-browser or old browser",
        )

    # Fallback: Origin vs Host comparison for older browsers
    # Note: On pre-2023 browsers, HTTP→HTTPS transitions may cause mismatches
    # (Origin shows :443, request sees :80 if TLS terminated upstream).
    # HSTS helps here; otherwise add external origins to CSRF_TRUSTED_ORIGINS.
    if origin == "null":
        return False, "CSRF rejected: Null Origin header"

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
                host_match = origin_host.lower() == request_host.lower()
                port_match = origin_port == int(request_port)

                if host_match and port_match:
                    return (
                        True,
                        f"CSRF allowed: Same-origin request - Origin {origin} matches Host {host}",
                    )

                # Build detailed error message based on what mismatched
                if host_match:
                    # Port mismatch only - show ports since they're relevant
                    return (
                        False,
                        f"CSRF rejected: Origin {origin_host}:{origin_port} does not match Host {request_host}:{request_port} (port mismatch)",
                    )
                elif port_match:
                    # Host mismatch only - no need to show ports
                    return (
                        False,
                        f"CSRF rejected: Origin {origin_host} does not match Host {request_host}",
                    )
                else:
                    # Both mismatch - show full details
                    return (
                        False,
                        f"CSRF rejected: Origin {origin_host}:{origin_port} does not match Host {request_host}:{request_port}",
                    )
        except ValueError:
            pass

    # Origin present but couldn't parse/compare properly
    return (
        False,
        f"CSRF rejected: Origin {origin} could not be validated against Host {request.host}",
    )

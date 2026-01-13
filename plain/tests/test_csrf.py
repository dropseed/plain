from typing import Any
from unittest.mock import patch

import pytest

from plain.csrf.middleware import CsrfViewMiddleware
from plain.test import RequestFactory


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_safe_methods_allowed(method):
    """Safe HTTP methods should always be allowed."""
    rf = RequestFactory()
    csrf_middleware = CsrfViewMiddleware(lambda request: None)

    request = rf.generic(method, "/test/")
    allowed, reason = csrf_middleware.should_allow_request(request)

    assert allowed is True
    assert f"Safe HTTP method: {method}" in reason


@pytest.mark.parametrize(
    ("sec_fetch_site", "expected_allowed", "expected_reason_contains"),
    [
        ("same-origin", True, "Same-origin request from Sec-Fetch-Site: same-origin"),
        ("none", True, "Same-origin request from Sec-Fetch-Site: none"),
        (
            "cross-site",
            False,
            "Cross-origin request from Sec-Fetch-Site: cross-site",
        ),
        (
            "same-site",
            False,
            "Cross-origin request from Sec-Fetch-Site: same-site",
        ),
    ],
)
def test_sec_fetch_site_header(
    sec_fetch_site, expected_allowed, expected_reason_contains
):
    """Test various Sec-Fetch-Site header values."""
    rf = RequestFactory()
    csrf_middleware = CsrfViewMiddleware(lambda request: None)

    request = rf.post("/test/", headers={"Sec-Fetch-Site": sec_fetch_site})
    allowed, reason = csrf_middleware.should_allow_request(request)

    assert allowed is expected_allowed
    assert expected_reason_contains in reason


@pytest.mark.parametrize(
    ("origin", "trusted_origins", "expected_allowed", "expected_reason_contains"),
    [
        # Trusted origins that should be allowed
        (
            "https://trusted.example.com",
            ["https://trusted.example.com"],
            True,
            "Trusted origin: https://trusted.example.com",
        ),
        (
            "https://api.example.com:8443",
            ["https://api.example.com:8443"],
            True,
            "Trusted origin: https://api.example.com:8443",
        ),
        # Untrusted origins that should continue to host check (and fail)
        (
            "https://untrusted.example.com",
            ["https://trusted.example.com"],
            False,
            "does not match Host",
        ),
    ],
)
def test_trusted_origins(
    origin, trusted_origins, expected_allowed, expected_reason_contains
):
    """Test trusted origins allow-list functionality."""
    rf = RequestFactory()
    csrf_middleware = CsrfViewMiddleware(lambda request: None)

    with patch("plain.csrf.middleware.settings") as mock_settings:
        mock_settings.CSRF_TRUSTED_ORIGINS = trusted_origins

        request = rf.post("/test/", headers={"Origin": origin})
        allowed, reason = csrf_middleware.should_allow_request(request)

        assert allowed is expected_allowed
        assert expected_reason_contains in reason


@pytest.mark.parametrize(
    "headers",
    [
        {},  # No headers
        {"Origin": ""},  # Empty origin header
    ],
)
def test_old_browser_fallback(headers):
    """Requests without proper headers should be allowed (old browsers)."""
    rf = RequestFactory()
    csrf_middleware = CsrfViewMiddleware(lambda request: None)

    request = rf.post("/test/", headers=headers)
    allowed, reason = csrf_middleware.should_allow_request(request)

    assert allowed is True
    assert (
        "No Origin or Sec-Fetch-Site header - likely non-browser or old browser"
        in reason
    )


@pytest.mark.parametrize(
    ("origin", "expected_allowed", "expected_reason_contains"),
    [
        # Origin matches host - should be allowed
        (
            "https://testserver",
            True,
            "Same-origin request - Origin https://testserver matches Host testserver",
        ),
        (
            "https://testserver:443",
            True,
            "Same-origin request - Origin https://testserver:443 matches Host testserver",
        ),
        # Various rejection cases
        ("null", False, "Null Origin header"),
        ("https://attacker.com", False, "does not match Host"),
        ("https://sub.testserver", False, "does not match Host"),
        ("https://example.com:8080", False, "does not match Host"),
        ("http://example.com", False, "does not match Host"),
    ],
)
def test_origin_host_comparison(origin, expected_allowed, expected_reason_contains):
    """Test Origin vs Host header comparison scenarios."""
    rf = RequestFactory()
    csrf_middleware = CsrfViewMiddleware(lambda request: None)

    # Configure request based on the origin
    request_kwargs: dict[str, Any] = {"headers": {"Origin": origin}}
    if origin == "https://testserver:443":
        request_kwargs.update(
            {
                "SERVER_NAME": "testserver",
                "SERVER_PORT": "443",
                "secure": True,
            }
        )
    elif origin == "https://testserver":
        request_kwargs["secure"] = True

    request = rf.post("/test/", **request_kwargs)
    allowed, reason = csrf_middleware.should_allow_request(request)

    assert allowed is expected_allowed
    assert expected_reason_contains in reason


def test_invalid_origin_url():
    """Invalid Origin URLs should be rejected."""
    rf = RequestFactory()
    csrf_middleware = CsrfViewMiddleware(lambda request: None)

    request = rf.post("/test/", headers={"Origin": "not-a-valid-url"})
    allowed, reason = csrf_middleware.should_allow_request(request)

    assert allowed is False
    assert "could not be validated against Host" in reason


def test_sec_fetch_site_priority_over_origin_check():
    """Sec-Fetch-Site should take priority over Origin vs Host check."""
    rf = RequestFactory()
    csrf_middleware = CsrfViewMiddleware(lambda request: None)

    # This would normally match (same host) but Sec-Fetch-Site rejects it first
    request = rf.post(
        "/test/",
        headers={"Origin": "https://testserver", "Sec-Fetch-Site": "cross-site"},
        secure=True,
    )
    allowed, reason = csrf_middleware.should_allow_request(request)

    assert allowed is False
    assert "Sec-Fetch-Site" in reason


@pytest.mark.parametrize(
    ("exempt_patterns", "test_path", "expected_allowed", "expected_reason_fragment"),
    [
        # Basic patterns
        (
            [r"^/api/", r"/webhooks/github/"],
            "/api/users/",
            True,
            "matches exempt pattern ^/api/",
        ),
        (
            [r"^/api/", r"/webhooks/github/"],
            "/webhooks/github/push",
            True,
            "matches exempt pattern /webhooks/github/",
        ),
        (
            [r"^/api/", r"/webhooks/github/"],
            "/admin/users/",
            False,
            "does not match Host",
        ),
        # Advanced regex patterns
        (
            [r"^/api/v\d+/", r"/webhooks/.*", r"/health$"],
            "/api/v1/users/",
            True,
            "matches exempt pattern ^/api/v\\d+/",
        ),
        (
            [r"^/api/v\d+/", r"/webhooks/.*", r"/health$"],
            "/api/v2/posts/",
            True,
            "matches exempt pattern ^/api/v\\d+/",
        ),
        (
            [r"^/api/v\d+/", r"/webhooks/.*", r"/health$"],
            "/webhooks/github/push",
            True,
            "matches exempt pattern /webhooks/.*",
        ),
        (
            [r"^/api/v\d+/", r"/webhooks/.*", r"/health$"],
            "/webhooks/stripe/payment",
            True,
            "matches exempt pattern /webhooks/.*",
        ),
        (
            [r"^/api/v\d+/", r"/webhooks/.*", r"/health$"],
            "/health",
            True,
            "matches exempt pattern /health$",
        ),
        # Edge cases - exact match should not match with suffix
        (
            [r"^/api/v\d+/", r"/webhooks/.*", r"/health$"],
            "/health-check",
            False,
            "does not match Host",
        ),
        (
            [r"^/api/v\d+/", r"/webhooks/.*", r"/health$"],
            "/admin/users/",
            False,
            "does not match Host",
        ),
        # Empty exempt paths list
        ([], "/api/users/", False, "does not match Host"),
    ],
)
def test_path_based_csrf_exemption(
    exempt_patterns, test_path, expected_allowed, expected_reason_fragment
):
    """Path-based CSRF exemption with various regex patterns should work correctly."""
    from plain.runtime import settings

    # Save original setting
    original_exempt_paths = settings.CSRF_EXEMPT_PATHS

    try:
        # Set up exempt regex patterns
        settings.CSRF_EXEMPT_PATHS = exempt_patterns

        # Need to recreate middleware to compile new patterns
        rf = RequestFactory()
        csrf_middleware = CsrfViewMiddleware(lambda request: None)

        # Test path with malicious origin to ensure exemption works
        request = rf.post(test_path, headers={"Origin": "https://attacker.com"})
        allowed, reason = csrf_middleware.should_allow_request(request)

        assert allowed is expected_allowed
        assert expected_reason_fragment in reason

    finally:
        # Restore original setting
        settings.CSRF_EXEMPT_PATHS = original_exempt_paths


def test_request_factory_naturally_bypasses_csrf():
    """Test that RequestFactory naturally bypasses CSRF due to missing headers.

    This demonstrates why enforce_csrf_checks was removed - it's redundant
    because test clients naturally lack browser headers and thus bypass CSRF anyway.
    """
    rf = RequestFactory()
    csrf_middleware = CsrfViewMiddleware(lambda request: None)

    # Create a POST request with NO Origin or Sec-Fetch-Site headers (typical for test clients)
    request = rf.post("/test/")

    # Verify no headers are present
    assert request.headers.get("Origin") is None
    assert request.headers.get("Sec-Fetch-Site") is None

    # This should be allowed due to "No Origin or Sec-Fetch-Site header"
    allowed, reason = csrf_middleware.should_allow_request(request)
    assert allowed is True
    assert (
        "No Origin or Sec-Fetch-Site header - likely non-browser or old browser"
        in reason
    )


def test_middleware_integration_rejected_request():
    """Rejected requests should raise SuspiciousOperationError400 without calling next."""
    from unittest.mock import Mock

    from plain.http import SuspiciousOperationError400

    rf = RequestFactory()
    mock_get_response = Mock()
    csrf_middleware = CsrfViewMiddleware(mock_get_response)

    request = rf.post("/test/", headers={"Origin": "https://attacker.com"})

    # Should raise SuspiciousOperationError400
    with pytest.raises(SuspiciousOperationError400) as exc_info:
        csrf_middleware.process_request(request)

    # Should not call next middleware
    mock_get_response.assert_not_called()

    # Exception message should contain the reason
    assert "does not match Host" in str(exc_info.value)

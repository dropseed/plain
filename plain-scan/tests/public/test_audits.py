"""Tests for individual security audits.

Each audit reads a ``requests.Response`` off the scanner and returns an
``AuditResult``. We drive them with synthetic responses so no network access
is required.
"""

from __future__ import annotations

import requests
from requests.cookies import RequestsCookieJar
from requests.structures import CaseInsensitiveDict

from plain.scan.audits import (
    ContentTypeOptionsAudit,
    FrameOptionsAudit,
    HSTSAudit,
    StatusCodeAudit,
    TLSAudit,
)
from plain.scan.scanner import Scanner


def make_response(*, headers=None, status_code=200, url="https://example.com/"):
    """Build a synthetic ``requests.Response`` for driving audits offline."""
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response.headers = CaseInsensitiveDict(headers or {})
    response.history = []
    response.cookies = RequestsCookieJar()
    return response


def run_audit(audit, **response_kwargs):
    scanner = Scanner(response_kwargs.get("url", "https://example.com/"))
    scanner.response = make_response(**response_kwargs)
    return audit.check(scanner)


# --- X-Content-Type-Options ------------------------------------------------


def test_content_type_options_missing_is_not_detected():
    result = run_audit(ContentTypeOptionsAudit())
    assert result.detected is False
    # Required audit that isn't detected fails.
    assert result.passed is False


def test_content_type_options_nosniff_passes():
    result = run_audit(
        ContentTypeOptionsAudit(),
        headers={"X-Content-Type-Options": "nosniff"},
    )
    assert result.detected is True
    assert result.passed is True


def test_content_type_options_wrong_value_fails():
    result = run_audit(
        ContentTypeOptionsAudit(),
        headers={"X-Content-Type-Options": "sniff"},
    )
    assert result.detected is True
    assert result.passed is False


def test_content_type_options_header_is_case_insensitive():
    # requests treats headers case-insensitively; a lowercased name still works.
    result = run_audit(
        ContentTypeOptionsAudit(),
        headers={"x-content-type-options": "nosniff"},
    )
    assert result.passed is True


# --- HSTS -------------------------------------------------------------------


def test_hsts_missing_is_not_detected():
    result = run_audit(HSTSAudit())
    assert result.detected is False
    assert result.passed is False


def test_hsts_fully_configured_passes():
    result = run_audit(
        HSTSAudit(),
        headers={
            "Strict-Transport-Security": (
                "max-age=63072000; includeSubDomains; preload"
            )
        },
    )
    assert result.detected is True
    assert result.passed is True


def test_hsts_short_max_age_fails_that_check():
    result = run_audit(
        HSTSAudit(),
        headers={
            "Strict-Transport-Security": ("max-age=100; includeSubDomains; preload")
        },
    )
    assert result.detected is True
    assert result.passed is False
    max_age_check = next(c for c in result.checks if c.name == "max-age")
    assert max_age_check.passed is False


# --- X-Frame-Options --------------------------------------------------------


def test_frame_options_deny_passes():
    result = run_audit(
        FrameOptionsAudit(),
        headers={"X-Frame-Options": "DENY"},
    )
    assert result.passed is True


def test_frame_options_invalid_value_fails():
    result = run_audit(
        FrameOptionsAudit(),
        headers={"X-Frame-Options": "ALLOWALL"},
    )
    assert result.detected is True
    assert result.passed is False


# --- Status code ------------------------------------------------------------


def test_status_code_200_passes():
    result = run_audit(StatusCodeAudit(), status_code=200)
    assert result.passed is True


def test_status_code_500_fails_and_is_required():
    result = run_audit(StatusCodeAudit(), status_code=500)
    assert result.required is True
    assert result.passed is False
    # The server-error branch must actually be reached (see the __bool__ note
    # in status_code.py) rather than the "unable to determine" fallback.
    assert "500" in result.checks[0].message


def test_status_code_404_is_not_required():
    result = run_audit(StatusCodeAudit(), status_code=404)
    # A 4xx is downgraded to non-required (could be an expected 404).
    assert result.required is False
    assert "404" in result.checks[0].message


# --- TLS offline branches ---------------------------------------------------


def test_tls_reports_fetch_exception():
    scanner = Scanner("https://expired.example.com/")
    scanner.fetch_exception = Exception("SSL: CERTIFICATE_VERIFY_FAILED")
    result = TLSAudit().check(scanner)

    assert result.detected is True
    assert result.passed is False
    assert "Certificate verification failed" in result.checks[0].message


def test_tls_skipped_for_non_https_url():
    # A plain-HTTP target has no TLS to audit; it must not open a socket.
    result = run_audit(TLSAudit(), url="http://example.com/", status_code=200)
    assert result.detected is False

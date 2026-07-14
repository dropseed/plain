"""Tests for the Scanner orchestration, driven offline.

Setting ``scanner.response`` before calling ``scan()`` makes ``fetch()``
return the cached response without any network access. An ``http://`` URL is
used so the TLS audit short-circuits instead of opening a socket.
"""

from __future__ import annotations

import requests
from requests.cookies import RequestsCookieJar
from requests.structures import CaseInsensitiveDict

from plain.scan.scanner import Scanner


def make_response(*, headers=None, status_code=200, url="https://example.com/"):
    """Build a synthetic ``requests.Response`` for driving the scanner offline."""
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response.headers = CaseInsensitiveDict(headers or {})
    response.history = []
    response.cookies = RequestsCookieJar()
    return response


SECURE_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def test_scan_runs_every_audit():
    scanner = Scanner("http://example.com/")
    scanner.response = make_response(url="http://example.com/", headers=SECURE_HEADERS)

    result = scanner.scan()

    # One AuditResult per configured audit.
    assert len(result.audits) == len(scanner.audits)
    assert result.url == "http://example.com/"


def test_disabled_audit_is_marked_and_excluded():
    scanner = Scanner("http://example.com/", disabled_audits={"hsts"})
    scanner.response = make_response(url="http://example.com/", headers=SECURE_HEADERS)

    result = scanner.scan()

    hsts = next(a for a in result.audits if a.name.startswith("HTTP Strict"))
    assert hsts.disabled is True
    assert hsts.passed is True  # disabled audits never fail the scan

    # Disabled audits are excluded from the totals.
    assert result.total_count == len(scanner.audits) - 1


def test_missing_security_headers_produce_failures():
    scanner = Scanner("http://example.com/")
    # No security headers at all.
    scanner.response = make_response(url="http://example.com/", headers={})

    result = scanner.scan()

    assert result.failed_count > 0
    assert result.passed is False

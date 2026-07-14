"""Tests for the result dataclasses' pass/fail logic and serialization."""

from __future__ import annotations

from plain.scan.results import AuditResult, CheckResult, ScanResult

PASS = CheckResult(name="c", passed=True, message="ok")
FAIL = CheckResult(name="c", passed=False, message="bad")


def test_required_audit_not_detected_fails():
    audit = AuditResult(name="A", detected=False, required=True)
    assert audit.passed is False


def test_optional_audit_not_detected_passes():
    audit = AuditResult(name="A", detected=False, required=False)
    assert audit.passed is True


def test_detected_audit_passes_only_when_all_checks_pass():
    assert AuditResult(name="A", detected=True, checks=[PASS, PASS]).passed is True
    assert AuditResult(name="A", detected=True, checks=[PASS, FAIL]).passed is False


def test_disabled_audit_always_passes():
    audit = AuditResult(name="A", detected=False, required=True, disabled=True)
    assert audit.passed is True


def test_scan_result_counts_exclude_disabled():
    scan = ScanResult(
        url="https://example.com/",
        audits=[
            AuditResult(name="ok", detected=True, checks=[PASS]),
            AuditResult(name="bad", detected=True, checks=[FAIL]),
            AuditResult(name="off", detected=False, disabled=True),
        ],
    )
    assert scan.passed_count == 1
    assert scan.failed_count == 1
    assert scan.total_count == 2  # disabled excluded
    assert scan.passed is False  # one failing audit


def test_empty_scan_result_does_not_pass():
    assert ScanResult(url="https://example.com/", audits=[]).passed is False


def test_scan_result_round_trips_through_dict():
    scan = ScanResult(
        url="https://example.com/",
        audits=[
            AuditResult(
                name="HSTS",
                detected=True,
                required=True,
                checks=[PASS, FAIL],
                description="desc",
            ),
        ],
    )
    restored = ScanResult.from_dict(scan.to_dict())

    assert restored.url == scan.url
    assert len(restored.audits) == 1
    audit = restored.audits[0]
    assert audit.name == "HSTS"
    assert audit.detected is True
    assert [c.passed for c in audit.checks] == [True, False]
    assert restored.passed == scan.passed

from __future__ import annotations

import pytest
from plain.email.backends import (
    CONSOLE_BACKEND,
    LOCMEM_BACKEND,
    PREVIEW_BACKEND,
    SMTP_BACKEND,
)
from plain.email.preflight import CheckEmailBackend, CheckEmailSMTPHost
from plain.runtime import settings


@pytest.mark.parametrize("backend", [CONSOLE_BACKEND, PREVIEW_BACKEND, LOCMEM_BACKEND])
def test_non_delivering_backend_is_an_error(monkeypatch, backend):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", backend)

    results = CheckEmailBackend().run()

    assert len(results) == 1
    assert results[0].id == "email.backend_does_not_deliver"
    assert not results[0].warning


def test_smtp_backend_passes(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", SMTP_BACKEND)

    assert CheckEmailBackend().run() == []


def test_third_party_backend_passes(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "myapp.email.SendgridBackend")

    assert CheckEmailBackend().run() == []


def test_smtp_host_left_at_default_warns(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", SMTP_BACKEND)
    monkeypatch.setattr(settings, "EMAIL_HOST", "localhost")

    results = CheckEmailSMTPHost().run()

    assert len(results) == 1
    assert results[0].id == "email.smtp_host_is_default"
    assert results[0].warning


def test_smtp_host_configured_passes(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", SMTP_BACKEND)
    monkeypatch.setattr(settings, "EMAIL_HOST", "smtp.example.com")

    assert CheckEmailSMTPHost().run() == []


def test_smtp_host_not_checked_for_other_backends(monkeypatch):
    """The backend check already covers these — don't report the host too."""
    monkeypatch.setattr(settings, "EMAIL_BACKEND", CONSOLE_BACKEND)
    monkeypatch.setattr(settings, "EMAIL_HOST", "localhost")

    assert CheckEmailSMTPHost().run() == []

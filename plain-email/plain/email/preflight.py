"""Deploy checks for email configuration.

Registered with `deploy=True`, so they run under `plain preflight --deploy`
and anywhere else deploy checks are included — the admin preflight view and
the toolbar badge pull them in whenever `DEBUG` is False. They exist only
when `plain.email` is installed, since preflight autodiscovery imports this
module per installed package.
"""

from __future__ import annotations

from plain.preflight import PreflightCheck, PreflightResult, register_check
from plain.runtime import settings

from .backends import CONSOLE_BACKEND, LOCMEM_BACKEND, PREVIEW_BACKEND, SMTP_BACKEND
from .default_settings import EMAIL_HOST as DEFAULT_EMAIL_HOST

# What each non-delivering backend does with a message instead of sending it.
NON_DELIVERING_BACKENDS = {
    CONSOLE_BACKEND: "prints email to the console",
    PREVIEW_BACKEND: "writes email to .eml files in .plain/emails/",
    LOCMEM_BACKEND: "keeps email in memory for tests",
}


@register_check(name="email.backend", deploy=True)
class CheckEmailBackend(PreflightCheck):
    """Ensures EMAIL_BACKEND actually delivers email in production deployment."""

    def run(self) -> list[PreflightResult]:
        behavior = NON_DELIVERING_BACKENDS.get(settings.EMAIL_BACKEND)
        if not behavior:
            return []

        return [
            PreflightResult(
                fix=f"EMAIL_BACKEND {behavior} instead of delivering it. "
                f"Set EMAIL_BACKEND={SMTP_BACKEND!r} (or another delivering backend) "
                "so password resets, login links, and other email reach recipients. "
                "Sending succeeds silently with this backend, so nothing else will "
                "report the loss.",
                id="email.backend_does_not_deliver",
            )
        ]


@register_check(name="email.smtp_host", deploy=True)
class CheckEmailSMTPHost(PreflightCheck):
    """Ensures the SMTP backend points at a mail server in production deployment."""

    def run(self) -> list[PreflightResult]:
        if settings.EMAIL_BACKEND != SMTP_BACKEND:
            # A non-delivering backend is email.backend's to report, and a
            # third-party backend may not read EMAIL_HOST at all.
            return []

        if not settings.EMAIL_HOST:
            # smtplib skips connecting when the host is empty, so the first
            # send raises SMTPServerDisconnected. Never intentional.
            return [
                PreflightResult(
                    fix="EMAIL_HOST is empty while using the SMTP backend, so every send fails "
                    "with SMTPServerDisconnected. Set EMAIL_HOST to your mail server.",
                    id="email.smtp_host_empty",
                )
            ]

        if settings.EMAIL_HOST == DEFAULT_EMAIL_HOST:
            return [
                PreflightResult(
                    fix=f"EMAIL_HOST is still the default {DEFAULT_EMAIL_HOST!r} while using the "
                    "SMTP backend. That only delivers if a mail relay is running on this host — "
                    "otherwise every send fails. Set EMAIL_HOST to your mail server, or silence "
                    "this result if you do run a local relay.",
                    id="email.smtp_host_is_default",
                    warning=True,
                )
            ]

        return []
